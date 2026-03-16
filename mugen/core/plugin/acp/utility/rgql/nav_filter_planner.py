"""Plan nested navigation property paths for RGQL filtering and ordering."""

from typing import Callable

from mugen.core.contract.gateway.storage.rdbms.types import RelatedPathHop
from mugen.core.utility.rgql.model import EdmModel
from mugen.core.utility.string.case_conversion_helper import title_to_snake


TableResolver = Callable[[str], str]  # edm_type_name -> logical table name


def plan_related_path(
    *,
    base_type_name: str,
    prop_path: str,
    model: EdmModel,
    table_resolver: TableResolver,
    max_nav_depth: int,
) -> tuple[list[RelatedPathHop], str] | None:
    """Plan a property path into related-table hops and a terminal field.

    Returns ``None`` when ``prop_path`` is not navigation-based (legacy flat mapping).
    Raises ``ValueError`` for unsupported/invalid nested navigation shapes.
    """
    parts = [p.strip() for p in prop_path.split("/") if p.strip()]
    if not parts:
        raise ValueError("Empty property path is not allowed.")

    current = model.try_get_type(base_type_name)
    if current is None:
        raise ValueError(f"Unknown EDM base type {base_type_name!r}.")

    # Non-nested paths can continue using the legacy flat mapping unless they
    # directly reference a navigation property.
    if len(parts) == 1:
        nav = current.nav_properties.get(parts[0])
        if nav is not None:
            if nav.target_type.is_collection:
                raise ValueError(
                    "To-many navigation paths are not supported directly; use any/all."
                )
            raise ValueError(
                "Navigation path must end in a scalar property, not a navigation."
            )
        return None

    nav_depth = 0
    hops: list[RelatedPathHop] = []

    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1

        nav = current.nav_properties.get(part)
        if nav is not None:
            if nav.target_type.is_collection:
                raise ValueError(
                    "To-many navigation paths are not supported directly; use any/all."
                )
            if not nav.source_fk:
                raise ValueError(
                    f"Navigation {part!r} on {current.name!r} has no source_fk."
                )

            nav_depth += 1
            if nav_depth > max_nav_depth:
                raise ValueError(
                    f"Nested navigation depth exceeds max ({max_nav_depth})."
                )

            source_table = _resolve_table_name(table_resolver, current.name)
            target_table = _resolve_table_name(table_resolver, nav.target_type.name)
            hops.append(
                RelatedPathHop(
                    source_table=source_table,
                    source_field=title_to_snake(nav.source_fk),
                    target_table=target_table,
                    target_field="id",
                )
            )

            target_type = model.try_get_type(nav.target_type.name)
            if target_type is None:
                raise ValueError(
                    f"Navigation {part!r} targets unknown EDM type "
                    f"{nav.target_type.name!r}."
                )
            current = target_type

            if is_last:
                raise ValueError(
                    "Navigation path must end in a scalar property, not a navigation."
                )
            continue

        prop = current.properties.get(part)
        if prop is not None:
            if not is_last:
                if hops:
                    raise ValueError(
                        "Nested navigation path may only traverse navigation "
                        "properties before the terminal scalar property."
                    )
                return None

            if not hops:  # pragma: no cover - guarded by non-nav early return above
                return None

            if prop.type.is_collection:
                raise ValueError(
                    "Collection-valued terminal properties are not supported."
                )

            term_type = model.try_get_type(prop.type.name)
            if term_type is not None and term_type.kind in {"entity", "complex"}:
                raise ValueError(
                    "Nested navigation path must end in a scalar property."
                )

            return hops, title_to_snake(prop.name)

        if part in model.types:
            raise ValueError("Type-cast segments are not supported in nested paths.")

        if hops:
            raise ValueError(
                f"Unknown segment {part!r} in nested navigation path {prop_path!r}."
            )
        return None

    raise ValueError(  # pragma: no cover - loop always returns or raises
        f"Invalid nested navigation path {prop_path!r}; "
        "expected a terminal scalar property."
    )


def _resolve_table_name(table_resolver: TableResolver, edm_type_name: str) -> str:
    try:
        table_name = table_resolver(edm_type_name)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise ValueError(
            f"Unable to resolve table for EDM type {edm_type_name!r}: {exc}"
        ) from exc
    if not table_name:
        raise ValueError(f"No table mapped for EDM type {edm_type_name!r}.")
    return table_name
