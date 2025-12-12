"""Helpers to materialize OData-style $expand trees onto in-memory entities.

This module walks EDM navigation properties using the RGQL expansion model
and invokes relational services to load related entities, attaching them to
the root entities according to configured naming conventions.
"""

from dataclasses import dataclass, fields
from typing import Any, Callable, Sequence


from mugen.core.contract.gateway.storage.rdbms.service_base import (
    IRelationalService,
)
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.utility.case_conversion_helper import snake_to_title, title_to_snake
from mugen.core.utility.rgql.model import EdmModel
from mugen.core.utility.rgql.url_parser import ExpandItem, RGQLQueryOptions
from mugen.core.utility.rgql_to_relational_helper import RGQLToRelationalAdapter

ServiceResolver = Callable[[str], IRelationalService[Any]]  # type_name -> service


@dataclass
class ExpansionContext:
    """Mutable expansion state for a single request."""

    model: EdmModel

    adapter: RGQLToRelationalAdapter

    service_resolver: ServiceResolver

    max_depth: int


def normalise_expand_levels(levels: int | str | None, max_depth: int) -> int:
    """."""
    if levels is None:
        return max_depth
    if isinstance(levels, str):
        # treat "max" (case-insensitive) as full depth
        if levels.lower() == "max":
            return max_depth
        # optional: raise for unknown strings
        raise ValueError(f"Unsupported $levels value: {levels!r}")
    # clamp to [0, max_depth]
    return max(0, min(levels, max_depth))


# pylint: disable=too-many-locals
# pylint: disable=too-many-arguments
# pylint: disable=too-many-branches
async def expand_navs_recursive(
    *,
    root_entity: Any,
    ctx: ExpansionContext,
    expand_item: ExpandItem,
    current_type_name: str,
    depth: int,
    levels_remaining: int,
) -> None:
    """
    Recursively materialise a single $expand item onto root_entity, using the EDM model
    and configured relational services. Supports both collection and single-valued
    navigation properties, plus $levels and a global max_depth guard.
    """
    # Stop if:
    # * there is nothing to expand, or
    # * there are no entities, or
    # * we are beyond the allowed depth for this branch.
    if (
        not expand_item
        or not root_entity
        or depth >= ctx.max_depth
        or depth >= levels_remaining
    ):
        return

    model = ctx.model

    # item.path is a string like "SystemUsers" or "Orders/Items"
    segments = [p for p in expand_item.path.split("/") if p]
    if not segments:
        return

    # For now we only support a single-hop navigation at this level.
    # Multi-hop paths (e.g. "Orders/Items") can be added later, or
    # expressed via nested item.expand.
    if len(segments) != 1:
        return

    edm_type = model.get_type(current_type_name)
    nav_name = segments[0]  # e.g. "SystemUsers"

    nav = edm_type.nav_properties.get(nav_name)
    if nav is None:
        return

    target_service = ctx.service_resolver(nav.target_type.name)
    if target_service is None:
        return

    entity_property = title_to_snake(nav_name)

    # Build relational query args for the *child* based on the expand item.
    child_opts = RGQLQueryOptions(
        filter=expand_item.filter,
        orderby=expand_item.orderby,
        top=expand_item.top,
        skip=expand_item.skip,
        select=expand_item.select,
        expand=expand_item.expand,
        apply=None,
        compute=None,
        search=expand_item.search,
        count=expand_item.count,
        format=None,
        schemaversion=None,
        skiptoken=None,
        deltatoken=None,
    )

    child_filter_groups, child_order_by, child_limit, child_offset = (
        ctx.adapter.build_relational_query(child_opts)
    )

    child_columns: Sequence[str] | None = None
    if child_opts.select:
        # Only root-level scalar properties for this nav for now
        child_columns = [title_to_snake(p) for p in child_opts.select if "/" not in p]

    if nav.target_type.is_collection:
        parent_filter = [
            FilterGroup(
                where={
                    f"{title_to_snake(current_type_name.split(".")[1])}_id": (
                        root_entity.id
                    ),
                },
            )
        ]

        children_by_parent = await target_service.list(
            columns=child_columns,
            filter_groups=parent_filter + (child_filter_groups or []),
            order_by=child_order_by or None,
            limit=child_limit,
            offset=child_offset,
        )

        collection: list[Any] = []
        for child in children_by_parent:
            if isinstance(child_opts.expand, list):
                for expansion in child_opts.expand:
                    await expand_navs_recursive(
                        root_entity=child,
                        ctx=ctx,
                        expand_item=expansion,
                        current_type_name=nav.target_type.name,
                        depth=depth + 1,
                        levels_remaining=min(
                            max(0, levels_remaining - 1),
                            normalise_expand_levels(expansion.levels, ctx.max_depth),
                        ),
                    )

            collection_item = {
                snake_to_title(field.name): getattr(child, field.name)
                for field in fields(child)
                if (
                    child_columns is None
                    or field.name in child_columns
                    or snake_to_title(field.name) in [x.path for x in child_opts.expand]
                )
                and (getattr(child, field.name) is not None)
                and not model.get_type(nav.target_type.name).property_redacted(
                    snake_to_title(field.name)
                )
            }

            collection.append(collection_item)

        if collection:
            setattr(root_entity, entity_property, collection)
    else:
        child_id = f"{title_to_snake(nav_name)}_id"
        child = await target_service.get(
            {"id": getattr(root_entity, child_id)}, columns=child_columns
        )

        if isinstance(child_opts.expand, list):
            for expansion in child_opts.expand:
                await expand_navs_recursive(
                    root_entity=child,
                    ctx=ctx,
                    expand_item=expansion,
                    current_type_name=nav.target_type.name,
                    depth=depth + 1,
                    levels_remaining=min(
                        max(0, levels_remaining - 1),
                        normalise_expand_levels(expansion.levels, ctx.max_depth),
                    ),
                )

        child_data = {}
        for field in fields(child):
            if (
                (
                    child_columns is None
                    or field.name in child_columns
                    or snake_to_title(field.name) in [x.path for x in child_opts.expand]
                )
                and (getattr(child, field.name) is not None)
                and not model.get_type(nav.target_type.name).property_redacted(
                    snake_to_title(field.name)
                )
            ):
                child_data[snake_to_title(field.name)] = getattr(child, field.name)

        if child_data:
            setattr(root_entity, entity_property, child_data)
