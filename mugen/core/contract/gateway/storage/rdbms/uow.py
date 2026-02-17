"""Provides an abstraction over a relational data store.

This interface exposes a very small, deliberately opinionated subset of
relational operations suitable for most read/write use-cases. It is
intentionally not a general-purpose query builder: callers are expected
to use equality filters, simple text filters and scalar comparison
filters, optionally combined with ordering and pagination.

Text filters are case-insensitive by default; callers can opt into
case-sensitive matching via the case_sensitive flag on TextFilter.

Filters are expressed as *sets of conjunctive groups*. Each group
represents a conjunction (logical AND) of simple predicates, and the
full set of groups is combined with logical OR. This corresponds to
Disjunctive Normal Form (DNF):

    (G1.predicates) OR (G2.predicates) OR ...

Implementations are free to map these groups to a single statement with
OR, or to multiple statements whose results are unioned.
"""

__all__ = ["IRelationalUnitOfWork"]

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from mugen.core.contract.gateway.storage.rdbms.types import (  # pylint: disable=unused-import
    OrderClause,
    Record,
    FilterGroup,
    RowVersionConflict,
)


class IRelationalUnitOfWork(ABC):
    """A transactional context for simple CRUD operations on flat tables.

    All methods operate on "logical" table names and rows represented as mapping objects
    (usually plain dicts).

    Optimistic concurrency via ``row_version``
    -----------------------------------------
    Implementations may support optimistic concurrency checks for updates and deletes
    when the caller supplies an expected version in the equality predicates::

        where={"id": ..., "row_version": expected_version}

    In that mode:
      - the UPDATE/DELETE should only succeed if the stored ``row_version`` matches
        the expected value,
      - implementations typically increment ``row_version`` on successful updates, and
      - if the write affects zero rows, :class:`RowVersionConflict` may be raised.
    """

    @abstractmethod
    async def count(
        self,
        table: str,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
    ) -> int:
        """Count records that match the given filter groups."""

    @abstractmethod
    async def insert(
        self,
        table: str,
        record: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> Record | None:
        """Insert a single record into `table`."""

    @abstractmethod
    async def get_one(
        self,
        table: str,
        where: Mapping[str, Any],
        *,
        columns: Sequence[str] | None = None,
    ) -> Record | None:
        """Fetch a single row matching the given equality predicates."""

    @abstractmethod
    async def find(  # pylint: disable=too-many-arguments
        self,
        table: str,
        *,
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderClause] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[Record]:
        """Run a select query with OR-of-AND filter semantics."""

    @abstractmethod
    async def find_partitioned_by_fk(  # pylint: disable=too-many-arguments
        self,
        table: str,
        *,
        fk_field: str,
        fk_values: Sequence[Any],
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderClause] | None = None,
        per_fk_limit: int | None = None,
        per_fk_offset: int | None = None,
        tie_breaker_field: str = "id",
    ) -> Sequence[Record]:
        """Fetch rows for multiple foreign-key owners with per-owner paging.

        Equivalent semantics to running N independent queries:
            WHERE fk_field = <one fk>
            ORDER BY ...
            OFFSET per_fk_offset LIMIT per_fk_limit

        But does it in one query using window functions.
        """

    @abstractmethod
    async def update_one(
        self,
        table: str,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> Record | None:
        """Update a single row with `changes`.

        If `where` includes a ``row_version`` key, implementations may treat it as an
        optimistic concurrency token.

        Raises
        ------
        RowVersionConflict
            If an optimistic concurrency check fails (most commonly when ``where``
            includes ``row_version`` and the UPDATE affects zero rows).
        """

    @abstractmethod
    async def delete_one(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> Record | None:
        """Delete a single row.

        If `where` includes a ``row_version`` key, implementations may treat it as an
        optimistic concurrency token.

        Raises
        ------
        RowVersionConflict
            If an optimistic concurrency check fails (most commonly when ``where``
            includes ``row_version`` and the DELETE affects zero rows).
        """

    @abstractmethod
    async def delete_many(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> None:
        """Delete multiple rows from `table`."""
