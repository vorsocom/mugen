"""Provides a generic base service for CRUD operations backed by IRelationalStorageGateway."""

from abc import ABC
from typing import Any, Generic, Mapping, Sequence, TypeVar

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import (
    Record,
    FilterGroup,
    OrderBy,
)

T = TypeVar("T")


class IRelationalService(Generic[T], ABC):
    """A generic base service for CRUD operations backed by IRelationalStorageGateway.

    This is intended as an implementation helper for concrete domain services.
    Subclasses provide:

      * the underlying table name
      * how to map Record -> domain entity
      * how to build a WHERE clause from an id
    """

    def __init__(
        self,
        de_type: T,
        table: str,
        rsg: IRelationalStorageGateway,
        **kwargs,
    ):
        self._de_type = de_type
        self._table = table
        self._rsg = rsg
        super().__init__(**kwargs)

    @property
    def table(self) -> str:
        """Logical table name understood by the gateway."""
        return self._table

    def _from_record(self, record: Record) -> T:
        """Map a raw record to a domain entity."""
        entity = self._de_type()
        for k, v in record.items():
            setattr(entity, k, v)
        return entity

    async def count(
        self,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
    ) -> int:
        """Count the number of rows matching filter_groups."""
        return await self._rsg.count_many(self.table, filter_groups=filter_groups)

    async def create(self, values: Mapping[str, Any]) -> T:
        """Create a single entity from raw column values."""
        row = await self._rsg.insert_one(self.table, dict(values))
        return self._from_record(row)

    async def get(
        self,
        where: Mapping[str, Any],
        *,
        columns: Sequence[str] | None = None,
    ) -> T | None:
        """Fetch a single entity matching `where`."""
        row = await self._rsg.get_one(self.table, where, columns=columns)
        return self._from_record(row) if row is not None else None

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
        rows = await self._rsg.find_many(
            self.table,
            columns=columns,
            filter_groups=filter_groups,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return [self._from_record(r) for r in rows]

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> T | None:
        """Update a single entity matching `where`.."""
        row = await self._rsg.update_one(
            self.table,
            where=where,
            changes=dict(changes),
        )
        return self._from_record(row) if row is not None else None

    async def delete(self, where: Mapping[str, Any]) -> None:
        """Delete a single entity matching `where`.."""
        await self._rsg.delete_one(self.table, where=where)
