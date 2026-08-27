"""Provides reusable validation for global billing references."""

from __future__ import annotations

__all__ = ["BillingReferenceService"]

from typing import Any, Generic, Mapping, TypeVar

from quart import abort

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService

T = TypeVar("T")


class BillingReferenceService(IRelationalService[T], Generic[T]):
    """Validate active global references and preserve currency snapshots."""

    _active_reference_tables: Mapping[str, tuple[str, str]] = {}
    _currency_snapshot = False

    async def _validated_changes(
        self,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = dict(values)
        for field_name, (table_name, label) in self._active_reference_tables.items():
            reference_id = payload.get(field_name)
            if reference_id is None:
                continue
            definition = await self._rsg.get_one(table_name, {"id": reference_id})
            if definition is None or not definition.get("is_active"):
                abort(400, f"{label} must reference an active global definition.")
            if self._currency_snapshot and field_name == "currency_definition_id":
                payload["currency"] = str(definition["code"]).upper()
        return payload

    async def create(self, values: Mapping[str, Any]) -> T:
        return await super().create(await self._validated_changes(values))

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> T | None:
        return await super().update(where, await self._validated_changes(changes))

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> T | None:
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=await self._validated_changes(changes),
        )
