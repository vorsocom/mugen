"""Provides a generic contract for services that provide CRUD operations."""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Sequence, Mapping, Any

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
    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> T | None:
        """Update a single entity matching `where`."""

    @abstractmethod
    async def delete(self, where: Mapping[str, Any]) -> None:
        """Delete a single entity matching `where`."""
