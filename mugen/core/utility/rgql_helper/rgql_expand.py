"""Helpers to materialize OData-style $expand trees onto in-memory entities.

This module walks EDM navigation properties using the RGQL expansion model
and invokes relational services to load related entities, attaching them to
the root entities according to configured naming conventions.
"""

from dataclasses import dataclass, field, fields
from typing import Any, Callable, Sequence

from mugen.core.contract.gateway.storage.rdbms.service_base import (
    IRelationalService,
)
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RelatedPathHop,
    ScalarFilter,
    ScalarFilterOp,
    TextFilter,
)
from mugen.core.utility.string.case_conversion_helper import (
    snake_to_title,
    title_to_snake,
)
from mugen.core.utility.rgql.model import EdmModel, EdmType
from mugen.core.utility.rgql.url_parser import ExpandItem, RGQLQueryOptions
from mugen.core.utility.rgql_helper.error import RGQLExpandError
from mugen.core.utility.rgql_helper.rgql_to_relational import (
    RGQLToRelationalAdapter,
)

DefaultWhereProvider = Callable[[str], dict[str, Any]]  # type_name -> constraints
EntitySerializationProvider = Callable[
    [object, object, list[str], set[str]],
    dict[str, Any],
]
PathPermissionProvider = Callable[[object, str], bool]
ServiceResolver = Callable[[str], IRelationalService[Any]]  # type_name -> service
NavPathPlanner = Callable[
    [str, str],
    tuple[Sequence[RelatedPathHop], str] | None,
]  # base_type_name, prop_path -> plan


# pylint: disable=too-many-locals
# pylint: disable=too-many-arguments
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
# pylint: disable=too-many-instance-attributes


def apply_to_filter_groups(
    filter_groups: Sequence[FilterGroup] | None,
    *,
    where: dict[str, Any] | None = None,
    scalars: Sequence[ScalarFilter] | None = None,
    texts: Sequence[TextFilter] | None = None,
) -> list[FilterGroup]:
    """Merge default filters into an exisitng sequence of filter groups."""
    if not where and not scalars and not texts:
        return filter_groups or []

    if not filter_groups:
        fg = FilterGroup()
        fg.where = dict(where) if where is not None else {}
        fg.scalar_filters = scalars if scalars is not None else []
        fg.text_filters = texts if texts is not None else []
        return [fg]

    merged: list[FilterGroup] = []
    for g in filter_groups:
        gcopy = FilterGroup()

        gcopy.where = dict(getattr(g, "where", {}))
        if where:
            gcopy.where.update(where)

        existing_scalars = list(getattr(g, "scalar_filters", None) or [])
        incoming_scalars = list(scalars or [])
        gcopy.scalar_filters = [*existing_scalars, *incoming_scalars]

        existing_texts = list(getattr(g, "text_filters", None) or [])
        incoming_texts = list(texts or [])
        gcopy.text_filters = [*existing_texts, *incoming_texts]

        existing_related_scalars = list(
            getattr(g, "related_scalar_filters", None) or []
        )
        gcopy.related_scalar_filters = [*existing_related_scalars]

        existing_related_texts = list(getattr(g, "related_text_filters", None) or [])
        gcopy.related_text_filters = [*existing_related_texts]

        merged.append(gcopy)
    return merged


def apply_to_where(
    where: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Merge default filters into and exisitng where clause."""
    if defaults:
        where.update(defaults)  # enforce
    return where


@dataclass
class ExpansionContext:
    """Mutable expansion state for a single request.

    service_resolver:
      - Resolves a entity set name (e.g. "Users") to a relational service.
      - Namespacing belongs in the resolver closure, not in this module.

    default_where_provider:
      - Returns enforced where constraints for a given EDM type name.
      - Examples: soft-delete exclusion, tenant scoping, row-level visibility.
      - This module treats it as an invariant (i.e., it is AND'ed in and cannot
        be overridden unless the provider returns {}).
    """

    model: EdmModel

    adapter: RGQLToRelationalAdapter

    serialization_provider: EntitySerializationProvider

    service_resolver: ServiceResolver

    path_permission_provider: PathPermissionProvider

    max_depth: int

    allow_expand_wildcard: bool

    default_top: int

    max_top: int

    max_skip: int

    max_select: int

    max_orderby: int

    max_expand_paths: int

    max_filter_terms: int

    nav_path_planner: NavPathPlanner | None = None

    default_where_provider: DefaultWhereProvider = lambda _type_name: {}

    permission_cache: dict[tuple[str, str], bool] = field(default_factory=dict)

    async def permitted(self, edm_type: EdmType, path: str) -> bool:
        """Lookup path permission in cache before calling path permission provider."""
        key = (edm_type.name, path)
        if key in self.permission_cache:
            return self.permission_cache[key]
        allowed = await self.path_permission_provider(edm_type, path)
        self.permission_cache[key] = allowed
        return allowed


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


def _augment_query_columns_for_nested_expands(
    *,
    edm_type: EdmType,
    expand_items: Sequence[ExpandItem] | None,
    query_columns: Sequence[str] | None,
) -> Sequence[str] | None:
    """Augment query_columns with join keys required by nested $expand.

    This prevents nested expansions from silently no-op'ing when the client uses
    $select to omit required foreign keys (e.g. expanding a single-valued nav
    requires the parent's source_fk to be present).
    """
    if query_columns is None or not expand_items:
        return query_columns

    required_cols: set[str] = {"id"}

    for exp in expand_items:
        nav_name = exp.path
        try:
            nav_prop = edm_type.nav_properties[nav_name]
        except KeyError:
            nav_prop = None
        if nav_prop is not None and not nav_prop.target_type.is_collection:
            required_cols.add(title_to_snake(nav_prop.source_fk))

    out = list(query_columns)
    for col in required_cols:
        if col not in out:
            out.append(col)
    return out


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
        or levels_remaining <= 0
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
        raise RGQLExpandError(400, "Multi-hop expand paths not supported.")

    edm_type = model.get_type(current_type_name)
    nav_name = segments[0]  # e.g. "SystemUsers"

    nav = edm_type.nav_properties.get(nav_name)
    if nav is None:
        return

    nav_type = model.get_type(nav.target_type.name)

    nav_service = ctx.service_resolver(nav_type.name)
    if nav_service is None:
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

    try:
        child_filter_groups, child_order_by, child_limit, child_offset = (
            ctx.adapter.build_relational_query(
                child_opts,
                path_planner=(
                    lambda path: ctx.nav_path_planner(nav_type.name, path)
                    if ctx.nav_path_planner is not None
                    else None
                ),
            )
        )
    except ValueError as exc:
        raise RGQLExpandError(400, str(exc)) from exc

    if child_order_by and len(child_order_by) > ctx.max_orderby:
        raise RGQLExpandError(
            400,
            f"Max $orderby ({ctx.max_orderby}) exceeded (expand recursion).",
        )

    if child_limit is None:
        child_limit = ctx.default_top

    if child_limit > ctx.max_top:
        raise RGQLExpandError(
            400,
            f"$top exceeds max ({ctx.max_top}) (expand recursion).",
        )

    if child_offset is None:
        child_offset = 0

    if child_offset > ctx.max_skip:
        raise RGQLExpandError(
            400,
            f"$skip exceeds max ({ctx.max_skip}) (expand recursion).",
        )

    if (
        isinstance(child_opts.expand, list)
        and any(ei.path == "*" for ei in child_opts.expand)
        and not ctx.allow_expand_wildcard
    ):
        raise RGQLExpandError(400, "Wildcard expansion not allowed (expand recursion).")

    child_expand_paths: set[str] = set()
    if child_opts.expand:
        child_opts.expand = [
            item
            for item in child_opts.expand
            if await ctx.permitted(nav_type, item.path)
        ]
        child_expand_paths = {item.path for item in child_opts.expand}

        if len(child_expand_paths) > ctx.max_expand_paths:
            raise RGQLExpandError(
                400,
                f"Max $expand paths ({ctx.max_expand_paths}) exceeded (expand"
                " recursion).",
            )

    child_columns: Sequence[str] | None = None
    if child_opts.select:
        if len(child_opts.select) > ctx.max_select:
            raise RGQLExpandError(
                400,
                f"Max $select ({ctx.max_select}) exceeded (expand recursion).",
            )

        # Only root-level scalar properties for this nav for now
        child_columns = [title_to_snake(p) for p in child_opts.select if "/" not in p]

    delete_filter = ctx.default_where_provider(nav_type.name)
    if nav.target_type.is_collection:
        # Filter deleted.
        child_filter_groups = apply_to_filter_groups(
            child_filter_groups,
            where=delete_filter,
        )

        # Filter by parent id.
        parent_fk = title_to_snake(nav.target_fk)
        child_filter_groups = apply_to_filter_groups(
            child_filter_groups,
            where={parent_fk: root_entity.id},  # Expansions assume parent PK is `id`.
        )

        if child_filter_groups:
            fg_sum = 0

            for fg in child_filter_groups:
                fg_sum += len(fg.where)
                fg_sum += len(fg.scalar_filters)
                fg_sum += len(fg.text_filters)
                fg_sum += len(getattr(fg, "related_scalar_filters", []))
                fg_sum += len(getattr(fg, "related_text_filters", []))

            if fg_sum > ctx.max_filter_terms:
                raise RGQLExpandError(
                    400,
                    f"Max filter terms ({ctx.max_filter_terms}) exceeded (expand"
                    " recursion).",
                )

        query_columns: Sequence[str] | None = child_columns
        if (
            isinstance(child_opts.expand, list)
            and child_opts.expand
            and query_columns is not None
        ):
            query_columns = _augment_query_columns_for_nested_expands(
                edm_type=nav_type,
                expand_items=child_opts.expand,
                query_columns=query_columns,
            )

        children_by_parent = await nav_service.list(
            columns=query_columns,
            filter_groups=child_filter_groups,
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
                        current_type_name=nav_type.name,
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
                    or snake_to_title(field.name) in child_expand_paths
                )
                and (getattr(child, field.name) is not None)
                and not nav_type.property_redacted(snake_to_title(field.name))
            }

            collection.append(collection_item)

        if collection:
            setattr(root_entity, entity_property, collection)
    else:
        # Filter by child id.
        source_fk = title_to_snake(nav.source_fk)
        target_id = getattr(root_entity, source_fk, None)
        if target_id is None:
            return

        where = {"id": target_id}

        # Filter deleted.
        where = apply_to_where(where, delete_filter)

        if len(where) > ctx.max_filter_terms:
            raise RGQLExpandError(
                400,
                f"Max filter terms ({ctx.max_filter_terms}) exceeded (expand"
                " recursion).",
            )

        query_columns: Sequence[str] | None = child_columns
        if (
            isinstance(child_opts.expand, list)
            and child_opts.expand
            and query_columns is not None
        ):
            query_columns = _augment_query_columns_for_nested_expands(
                edm_type=nav_type,
                expand_items=child_opts.expand,
                query_columns=query_columns,
            )
        child = await nav_service.get(where, columns=query_columns)

        if child is None:
            return

        if isinstance(child_opts.expand, list):
            for expansion in child_opts.expand:
                await expand_navs_recursive(
                    root_entity=child,
                    ctx=ctx,
                    expand_item=expansion,
                    current_type_name=nav_type.name,
                    depth=depth + 1,
                    levels_remaining=min(
                        max(0, levels_remaining - 1),
                        normalise_expand_levels(expansion.levels, ctx.max_depth),
                    ),
                )

        child_data = {}
        for f in fields(child):
            if (
                (
                    child_columns is None
                    or f.name in child_columns
                    or snake_to_title(f.name) in child_expand_paths
                )
                and (getattr(child, f.name) is not None)
                and not nav_type.property_redacted(snake_to_title(f.name))
            ):
                child_data[snake_to_title(f.name)] = getattr(child, f.name)

        if child_data:
            setattr(root_entity, entity_property, child_data)


async def expand_navs_bulk(
    *,
    root_entities: Sequence[Any],
    ctx: ExpansionContext,
    expand_item: ExpandItem,
    current_type_name: str,
    depth: int,
    levels_remaining: int,
) -> None:
    """
    Materialize one $expand item for many root entities with as few DB calls as possible.
    """
    if (
        not expand_item
        or not root_entities
        or depth >= ctx.max_depth
        or levels_remaining <= 0
    ):
        return

    segments = [p for p in expand_item.path.split("/") if p]
    if len(segments) != 1:
        raise RGQLExpandError(400, "Multi-hop expand paths not supported.")

    model = ctx.model
    edm_type = model.get_type(current_type_name)
    nav_name = segments[0]
    nav = edm_type.nav_properties.get(nav_name)
    if nav is None:
        return

    nav_type = model.get_type(nav.target_type.name)
    nav_service = ctx.service_resolver(nav_type.name)
    if nav_service is None:
        return

    entity_property = title_to_snake(nav_name)

    # Build child query options + relational args (same as recursive)
    child_opts = RGQLQueryOptions(
        filter=expand_item.filter,
        orderby=expand_item.orderby,
        top=expand_item.top,
        skip=expand_item.skip,
        select=expand_item.select,
        expand=expand_item.expand,
        search=expand_item.search,
        count=expand_item.count,
        apply=None,
        compute=None,
        format=None,
    )

    try:
        child_filter_groups, child_order_by, child_limit, child_offset = (
            ctx.adapter.build_relational_query(
                child_opts,
                path_planner=(
                    lambda path: ctx.nav_path_planner(nav_type.name, path)
                    if ctx.nav_path_planner is not None
                    else None
                ),
            )
        )
    except ValueError as exc:
        raise RGQLExpandError(400, str(exc)) from exc

    if child_order_by and len(child_order_by) > ctx.max_orderby:
        raise RGQLExpandError(
            400,
            f"Max $orderby ({ctx.max_orderby}) exceeded (expand recursion).",
        )

    if child_limit is None:
        child_limit = ctx.default_top

    if child_limit > ctx.max_top:
        raise RGQLExpandError(
            400,
            f"$top exceeds max ({ctx.max_top}) (expand recursion).",
        )

    if child_offset is None:
        child_offset = 0

    if child_offset > ctx.max_skip:
        raise RGQLExpandError(
            400,
            f"$skip exceeds max ({ctx.max_skip}) (expand recursion).",
        )

    if (
        isinstance(child_opts.expand, list)
        and any(ei.path == "*" for ei in child_opts.expand)
        and not ctx.allow_expand_wildcard
    ):
        raise RGQLExpandError(400, "Wildcard expansion not allowed (expand recursion).")

    child_expand_paths: set[str] = set()
    if child_opts.expand:
        child_opts.expand = [
            item
            for item in child_opts.expand
            if await ctx.permitted(nav_type, item.path)
        ]
        child_expand_paths = {item.path for item in child_opts.expand}

        if len(child_expand_paths) > ctx.max_expand_paths:
            raise RGQLExpandError(
                400,
                f"Max $expand paths ({ctx.max_expand_paths}) exceeded (expand"
                " recursion).",
            )

    child_columns: Sequence[str] | None = None
    if child_opts.select:
        if len(child_opts.select) > ctx.max_select:
            raise RGQLExpandError(
                400,
                f"Max $select ({ctx.max_select}) exceeded (expand recursion).",
            )

        # Only root-level scalar properties for this nav for now
        child_columns = [title_to_snake(p) for p in child_opts.select if "/" not in p]

    needs_child_id = bool(child_opts.expand)  # nested expansions need child.id

    # Columns used for querying children (may include extra join keys).
    query_columns: Sequence[str] | None = child_columns
    if (
        isinstance(child_opts.expand, list)
        and child_opts.expand
        and query_columns is not None
    ):
        query_columns = _augment_query_columns_for_nested_expands(
            edm_type=nav_type,
            expand_items=child_opts.expand,
            query_columns=query_columns,
        )

    delete_filter = ctx.default_where_provider(nav_type.name)

    if nav.target_type.is_collection:
        parent_fk = title_to_snake(nav.target_fk)

        parent_ids = [getattr(e, "id", None) for e in root_entities]
        parent_ids = [pid for pid in parent_ids if pid is not None]
        if not parent_ids:
            return

        child_filter_groups = apply_to_filter_groups(
            child_filter_groups,
            where=delete_filter,
        )

        if child_filter_groups:
            fg_sum = 0

            for fg in child_filter_groups:
                fg_sum += len(fg.where)
                fg_sum += len(fg.scalar_filters)
                fg_sum += len(fg.text_filters)
                fg_sum += len(getattr(fg, "related_scalar_filters", []))
                fg_sum += len(getattr(fg, "related_text_filters", []))

            if fg_sum > ctx.max_filter_terms:
                raise RGQLExpandError(
                    400,
                    f"Max filter terms ({ctx.max_filter_terms}) exceeded (expand"
                    " recursion).",
                )

        # Ensure the child rows include the FK used for partitioning.
        if query_columns is not None:
            if parent_fk not in query_columns:
                query_columns = [*query_columns, parent_fk]
            if needs_child_id and "id" not in query_columns:
                query_columns = [*query_columns, "id"]

        children = await nav_service.list_partitioned_by_fk(
            fk_field=parent_fk,
            fk_values=parent_ids,
            columns=query_columns,
            filter_groups=child_filter_groups,
            order_by=child_order_by,
            per_fk_limit=child_limit,
            per_fk_offset=child_offset,
        )

        # Group and attach
        by_parent: dict[Any, list[Any]] = {}
        for c in children:
            by_parent.setdefault(getattr(c, parent_fk, None), []).append(c)

        # Nested expands: bulk expand across ALL children
        if isinstance(child_opts.expand, list) and children:
            for exp in child_opts.expand:
                await expand_navs_bulk(
                    root_entities=children,
                    ctx=ctx,
                    expand_item=exp,
                    current_type_name=nav_type.name,
                    depth=depth + 1,
                    levels_remaining=min(
                        max(0, levels_remaining - 1),
                        normalise_expand_levels(exp.levels, ctx.max_depth),
                    ),
                )

        for e in root_entities:
            kids = by_parent.get(getattr(e, "id", None), [])
            if not kids:
                continue
            setattr(
                e,
                entity_property,
                [
                    ctx.serialization_provider(
                        k,
                        nav_type,
                        child_columns,
                        child_expand_paths,
                    )
                    for k in kids
                ],
            )

    else:
        source_fk = title_to_snake(nav.source_fk)
        target_ids = [getattr(e, source_fk, None) for e in root_entities]
        target_ids = [tid for tid in target_ids if tid is not None]
        if not target_ids:
            return

        source_filter = [
            ScalarFilter(
                field="id",
                op=ScalarFilterOp.IN,
                value=target_ids,
            )
        ]

        child_filter_groups = apply_to_filter_groups(
            child_filter_groups,
            where=delete_filter,
            scalars=source_filter,
        )

        if child_filter_groups:
            fg_sum = 0

            for fg in child_filter_groups:
                fg_sum += len(fg.where)
                fg_sum += len(fg.scalar_filters)
                fg_sum += len(fg.text_filters)
                fg_sum += len(getattr(fg, "related_scalar_filters", []))
                fg_sum += len(getattr(fg, "related_text_filters", []))

            if fg_sum > ctx.max_filter_terms:
                raise RGQLExpandError(
                    400,
                    f"Max filter terms ({ctx.max_filter_terms}) exceeded (expand"
                    " recursion).",
                )

        if query_columns is not None and "id" not in query_columns:
            query_columns = [*query_columns, "id"]

        children = await nav_service.list(
            columns=query_columns,
            filter_groups=child_filter_groups,
        )

        child_by_id = {getattr(c, "id", None): c for c in children}

        # Nested expands: bulk expand across found children
        if isinstance(child_opts.expand, list) and children:
            for exp in child_opts.expand:
                await expand_navs_bulk(
                    root_entities=children,
                    ctx=ctx,
                    expand_item=exp,
                    current_type_name=nav_type.name,
                    depth=depth + 1,
                    levels_remaining=min(
                        max(0, levels_remaining - 1),
                        normalise_expand_levels(exp.levels, ctx.max_depth),
                    ),
                )

        for e in root_entities:
            tid = getattr(e, source_fk, None)
            if tid is None:
                continue
            child = child_by_id.get(tid)
            if child is None:
                continue
            setattr(
                e,
                entity_property,
                ctx.serialization_provider(
                    child,
                    nav_type,
                    child_columns,
                    child_expand_paths,
                ),
            )
