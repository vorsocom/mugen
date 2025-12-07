"""Provides an abstract base class for repositories backed by IRelationalUnitOfWork."""

__all__ = ["IRelationalRepository"]

from abc import ABC, abstractmethod
from typing import Any, Generic, Mapping, Sequence, TypeVar

from mugen.core.contract.gateway.storage.rdbms.types import OrderBy, Record
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork

T = TypeVar("T")


class IRelationalRepository(ABC, Generic[T]):
    """An abstract base class for repositories backed by IRelationalUnitOfWork."""

    table: str  # subclasses must set this to the logical table name.

    def __init__(self, uow: IRelationalUnitOfWork) -> None:
        self._uow = uow

    # mapping.

    @abstractmethod
    def _from_row(self, row: Record) -> T:
        """Convert a DB row into a domain entity."""

    @abstractmethod
    def _to_row(self, entity: T) -> Mapping[str, Any]:
        """Convert a domain entity into a DB row mapping."""

    # common operations.

    async def get_by_pk(self, pk: Mapping[str, Any]) -> T | None:
        """See `IRelationalUnitOfWork.get_by_pk`."""
        row = await self._uow.get_by_pk(self.table, pk)
        return self._from_row(row) if row is not None else None

    async def find(
        self,
        where: Mapping[str, Any] | None = None,
        *,
        order_by: Sequence[OrderBy] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[T]:
        """See `IRelationalUnitOfWork.find`."""
        rows = self._uow.find(
            self.table,
            where=where,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return [self._from_row(r) for r in rows]

    async def add(self, entity: T) -> T:
        """See `IRelationalUnitOfWork.insert`."""
        row = self._to_row(entity)
        inserted = await self._uow.insert(self.table, row)
        return self._from_row(inserted)

    async def update(
        self,
        pk: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> T | None:
        """See `IRelationalUnitOfWork.update`."""
        updated = await self._uow.update(self.table, pk, changes)
        return self._from_row(updated) if updated is not None else None

    async def delete(self, pk: Mapping[str, Any]) -> None:
        """See `IRelationalUnitOfWork.delete`."""
        await self._uow.delete(self.table, pk)
