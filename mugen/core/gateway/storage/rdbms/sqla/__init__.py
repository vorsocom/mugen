"""Provides helper functions to build a TableRegistry from Base.metadata.tables."""

__all__ = [
    "build_table_registry_from_base",
    "build_table_registry_from_metadata",
]

from typing import Callable, Iterable, MutableMapping

from sqlalchemy import MetaData, Table
from sqlalchemy.orm import DeclarativeBase


def build_table_registry_from_metadata(
    metadata: MetaData,
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    name_mapper: Callable[[str], str] | None = None
) -> MutableMapping[str, Table]:
    """Build a TableRegistry from SQLAlchemy MetaData.

    Parameters
    ----------
    metadata:
        SQLAlchemy `MetaData` instance whose tables will be used.
    include:
        Optional iterbale of table names to include. If provided, only tables whose
        `Table.name` is in this collection will be exposed.
    exclude:
        Optional iterable of table names to exclude. Applied after `include`, if both
        are provided.
    name_mapper:
        Optiional function mapping the SQLAlchemy table name (`Table.name`) to the
        logical name used by the relational gateway. By default, the SQLAlchemy table
        name is used as the logical name.

    Returns
    -------
    TableRegistry
        A mapping of logical table name -> SQLAlchemy `Table`.

    Examples
    --------
    Basic usage with all tables:

    >>> registry = build_table_registry_from_metadata(Base.metadata)

    Using only selected tables:

    >>> registry = build_table_registry_from_metadata(
    ...     Base.metadata,
    ...     include={"users", "conversations"}
    ...)

    Using a custom logical naming scheme:

    >>> def to_logical(name: str) -> str:
    ...     # e.g., convert snake_case table names to camelCase logical names.
    ...     parts = name.split("_")
    ...     return parts[0] + join(p.title() for p in parts[1:])
    ...
    >>> registry = build_table_registry_from_metadata(
    ...     Base.metadata,
    ...     name_mapper=to_logical,
    ...)
    """
    include_set = set(include) if include is not None else None
    exclude_set = set(exclude) if exclude is not None else None
    mapper = name_mapper or (lambda n: n)

    result: dict[str, Table] = {}

    for table_name, table in metadata.tables.items():
        if include_set is not None and table_name not in include_set:
            continue
        if table_name in exclude_set:
            continue

        logical_name = mapper(table_name)
        result[logical_name] = table

    return result


def build_table_registry_from_base(
    base: type[DeclarativeBase],
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    name_mapper: Callable[[str], str] | None = None
) -> MutableMapping[str, Table]:
    """Build a TableRegistry from an SQLAlchemy declarative base.

    This is a small covenience wrapper around :func:`build_table_registry_from_metadata`
    that uses `base.metadata`.

    Parameters
    ----------
    base:
        Declarative base class whose `metadata` contains the tables to expose.
    include:
        Optional iterbale of table names to include. If provided, only tables whose
        `Table.name` is in this collection will be exposed.
    exclude:
        Optional iterable of table names to exclude. Applied after `include`, if both
        are provided.
    name_mapper:
        Optiional function mapping the SQLAlchemy table name (`Table.name`) to the
        logical name used by the relational gateway. By default, the SQLAlchemy table
        name is used as the logical name.

    Returns
    -------
    TableRegistry
        A mapping of logical table name -> SQLAlchemy `Table`.
    """
    return build_table_registry_from_metadata(
        base.metadata,
        include=include,
        exclude=exclude,
        name_mapper=name_mapper,
    )
