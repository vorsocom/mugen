"""Provides generic contracts for services that provide CRUD operations.

This module defines:
  - ICrudService: the base CRUD contract
  - ICrudServiceWithId: optional extension for "by id" convenience methods
  - ICrudServiceWithRowVersion: optional extension for row_version optimistic concurrency

Row-version optimistic concurrency
----------------------------------
If your tables expose an integer ``row_version`` column, services may enforce optimistic
concurrency for updates and deletes by requiring callers to supply an expected version
(``expected_row_version``). Implementations should constrain UPDATE/DELETE by
``row_version == expected_row_version`` and raise ``RowVersionConflict`` if the row
exists but the version does not match.

`RowVersionConflict` is defined in `mugen.core.contract.gateway.storage.rdbms.types`.
"""

__all__ = ["ICrudService", "ICrudServiceWithId", "ICrudServiceWithRowVersion"]

from abc import ABC, abstractmethod
from typing import Any, Generic, Mapping, Sequence, TypeVar

from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy

T = TypeVar("T")


class ICrudService(Generic[T], ABC):
    """A generic contract for services that provide CRUD operations."""

    @property
    @abstractmethod
    def table(self) -> str:
        """Logical table name understood by the gateway."""

    @abstractmethod
    async def count(
        self,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
    ) -> int:
        """Count the number of rows matching filter_groups."""

    @abstractmethod
    async def create(self, values: Mapping[str, Any]) -> T:
        """Create a single entity from raw column values."""

    @abstractmethod
    async def get(
        self,
        where: Mapping[str, Any],
        *,
        columns: Sequence[str] | None = None,
    ) -> T | None:
        """Fetch a single entity matching `where`."""

    @abstractmethod
    async def list(  # pylint: disable=too-many-arguments
        self,
        *,
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderBy] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[T]:
        """Fetch multiple entities with optional filters and pagination."""

    @abstractmethod
    async def list_partitioned_by_fk(  # pylint: disable=too-many-arguments
        self,
        *,
        fk_field: str,
        fk_values: Sequence[Any],
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderBy] | None = None,
        per_fk_limit: int | None = None,
        per_fk_offset: int | None = None,
    ) -> Sequence[T]:
        """Fetch rows for multiple foreign-key owners with per-owner paging.

        Equivalent semantics to running N independent queries:
            WHERE fk_field = <one fk>
            ORDER BY ...
            OFFSET per_fk_offset LIMIT per_fk_limit

        But does it in one query using window functions.
        """

    @abstractmethod
    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> T | None:
        """Update a single entity matching `where`."""

    @abstractmethod
    async def delete(self, where: Mapping[str, Any]) -> T | None:
        """Delete a single entity matching `where`.

        Returns
        -------
        T | None
            The deleted entity, or None if no row matched `where`.
        """


class ICrudServiceWithId(ICrudService[T], ABC):
    """Optional extension contract adding standard 'by id' convenience methods.

    Implementations define how an entity id maps to a WHERE mapping via where_for_id().
    This supports non-standard primary keys, composite keys, and tenant scoping.
    """

    @abstractmethod
    def where_for_id(self, entity_id: Any) -> Mapping[str, Any]:
        """Build a WHERE mapping for a single entity id."""

    @abstractmethod
    async def get_by_id(
        self,
        entity_id: Any,
        *,
        columns: Sequence[str] | None = None,
    ) -> T | None:
        """Fetch a single entity by id (via where_for_id)."""

    @abstractmethod
    async def update_by_id(
        self,
        entity_id: Any,
        changes: Mapping[str, Any],
    ) -> T | None:
        """Update a single entity by id (via where_for_id)."""

    @abstractmethod
    async def delete_by_id(self, entity_id: Any) -> T | None:
        """Delete a single entity by id (via where_for_id).

        Returns
        -------
        T | None
            The deleted entity, or None if no row matched.
        """


class ICrudServiceWithRowVersion(ICrudServiceWithId[T], ABC):
    """Optional extension contract for row_version optimistic concurrency.

    Concurrency semantics:
      - Callers supply expected_row_version (typically read from a prior GET).
      - Implementations constrain UPDATE/DELETE by row_version == expected_row_version.
      - If the row exists but the version differs, implementations should raise
        RowVersionConflict.

    Note: RowVersionConflict is defined in mugen.core.contract.gateway.storage.rdbms.types.
    """

    @abstractmethod
    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> T | None:
        """Update a single entity using optimistic concurrency.

        Returns
        -------
        T | None
            The updated entity, or None if no row matched the identity predicate.

        Raises
        ------
        RowVersionConflict
            If the row exists but row_version != expected_row_version.
        """

    @abstractmethod
    async def update_by_id_with_row_version(
        self,
        entity_id: Any,
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> T | None:
        """Update a single entity by id using optimistic concurrency.

        Returns
        -------
        T | None
            The updated entity, or None if no row matched the identity predicate.

        Raises
        ------
        RowVersionConflict
            If the row exists but row_version != expected_row_version.
        """

    @abstractmethod
    async def delete_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
    ) -> T | None:
        """Delete a single entity using optimistic concurrency.

        Returns
        -------
        T | None
            The deleted entity, or None if no row matched the identity predicate.

        Raises
        ------
        RowVersionConflict
            If the row exists but row_version != expected_row_version.
        """

    @abstractmethod
    async def delete_by_id_with_row_version(
        self,
        entity_id: Any,
        *,
        expected_row_version: int,
    ) -> T | None:
        """Delete a single entity by id using optimistic concurrency.

        Returns
        -------
        T | None
            The deleted entity, or None if no row matched the identity predicate.

        Raises
        ------
        RowVersionConflict
            If the row exists but row_version != expected_row_version.
        """
