"""Provides a generic base service for CRUD operations backed by IRelationalStorageGateway."""

from abc import ABC
from typing import Any, Mapping, Sequence, TypeVar, Generic

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import (
    Record,
    FilterGroup,
    OrderBy,
)

T = TypeVar("T")


class IRelationalService(ICrudServiceWithRowVersion[T], Generic[T], ABC):
    """A generic base service for CRUD operations backed by IRelationalStorageGateway.

    Notes on delete return values
    -----------------------------
    This base service propagates the gateway's `delete_one()` return value, allowing
    callers (e.g., API endpoints) to distinguish:
      - deleted row returned (success),
      - None (no row matched), and
      - RowVersionConflict raised (optimistic concurrency failure).
    """

    def __init__(
        self,
        de_type: Any,
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
        return self._table

    def _from_record(self, record: Record) -> T:
        entity = self._de_type()
        for k, v in record.items():
            setattr(entity, k, v)
        return entity

    # -------------------------------------------------------------------------
    # ID helpers (override if your PK is not "id" or you need composite scoping)
    # -------------------------------------------------------------------------
    def where_for_id(self, entity_id: Any) -> Mapping[str, Any]:
        return {"id": entity_id}

    async def get_by_id(
        self,
        entity_id: Any,
        *,
        columns: Sequence[str] | None = None,
    ) -> T | None:
        return await self.get(self.where_for_id(entity_id), columns=columns)

    async def update_by_id(
        self,
        entity_id: Any,
        changes: Mapping[str, Any],
    ) -> T | None:
        return await self.update(self.where_for_id(entity_id), changes)

    async def delete_by_id(self, entity_id: Any) -> T | None:
        return await self.delete(self.where_for_id(entity_id))

    # ----------------
    # Basic operations
    # ----------------
    async def count(
        self,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
    ) -> int:
        return await self._rsg.count_many(self.table, filter_groups=filter_groups)

    async def create(self, values: Mapping[str, Any]) -> T:
        row = await self._rsg.insert_one(self.table, dict(values))
        return self._from_record(row)

    async def get(
        self,
        where: Mapping[str, Any],
        *,
        columns: Sequence[str] | None = None,
    ) -> T | None:
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
        rows = await self._rsg.find_many(
            self.table,
            columns=columns,
            filter_groups=filter_groups,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return [self._from_record(r) for r in rows]

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
        rows = await self._rsg.find_many_partitioned_by_fk(
            self.table,
            fk_field=fk_field,
            fk_values=fk_values,
            columns=columns,
            filter_groups=filter_groups,
            order_by=order_by,
            per_fk_limit=per_fk_limit,
            per_fk_offset=per_fk_offset,
        )
        return [self._from_record(r) for r in rows]

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> T | None:
        row = await self._rsg.update_one(
            self.table,
            where=where,
            changes=dict(changes),
        )
        return self._from_record(row) if row is not None else None

    async def delete(self, where: Mapping[str, Any]) -> T | None:
        """Delete a single entity matching `where`.

        Returns
        -------
        T | None
            Deleted entity, or None if no row matched `where`.
        """
        deleted = await self._rsg.delete_one(self.table, where=where)
        return self._from_record(deleted) if deleted is not None else None

    # ------------------------------------------
    # Row-version optimistic concurrency helpers
    # ------------------------------------------
    def _with_row_version(
        self,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> Mapping[str, Any]:
        if not isinstance(expected_row_version, int):
            raise TypeError(
                f"expected_row_version must be int, got {type(expected_row_version)!r}"
            )
        merged: dict[str, Any] = dict(where)
        merged["row_version"] = expected_row_version
        return merged

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> T | None:
        where_with_version = self._with_row_version(where, expected_row_version)
        row = await self._rsg.update_one(
            self.table,
            where=where_with_version,
            changes=dict(changes),
        )
        return self._from_record(row) if row is not None else None

    async def update_by_id_with_row_version(
        self,
        entity_id: Any,
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> T | None:
        return await self.update_with_row_version(
            self.where_for_id(entity_id),
            expected_row_version=expected_row_version,
            changes=changes,
        )

    async def delete_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
    ) -> T | None:
        """Delete using optimistic concurrency.

        Returns
        -------
        T | None
            Deleted entity, or None if no row matched the identity predicate.

        Raises
        ------
        RowVersionConflict
            If the row exists but the expected row_version does not match.
        """
        where_with_version = self._with_row_version(where, expected_row_version)
        deleted = await self._rsg.delete_one(self.table, where=where_with_version)
        return self._from_record(deleted) if deleted is not None else None

    async def delete_by_id_with_row_version(
        self,
        entity_id: Any,
        *,
        expected_row_version: int,
    ) -> T | None:
        return await self.delete_with_row_version(
            self.where_for_id(entity_id),
            expected_row_version=expected_row_version,
        )
