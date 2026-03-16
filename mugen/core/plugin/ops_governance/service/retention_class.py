"""Provides a CRUD service for retention classes."""

__all__ = ["RetentionClassResolutionError", "RetentionClassService"]

import uuid
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.plugin.ops_governance.contract.service.retention_class import (
    IRetentionClassService,
)
from mugen.core.plugin.ops_governance.domain import RetentionClassDE
from mugen.core.plugin.ops_governance.domain.resource_type import (
    canonicalize_resource_type,
)


class RetentionClassResolutionError(RuntimeError):
    """Raised when retention class resolution cannot select one active class."""


class RetentionClassService(  # pylint: disable=too-few-public-methods
    IRelationalService[RetentionClassDE],
    IRetentionClassService,
):
    """A CRUD service for retention class metadata."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=RetentionClassDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def normalize_resource_type(value: str | None) -> str:
        """Normalize user/resource values into canonical retention type tokens."""
        return canonicalize_resource_type(value)

    async def create(self, values: Mapping[str, Any]) -> RetentionClassDE:
        payload = dict(values)
        payload["resource_type"] = self.normalize_resource_type(
            payload.get("resource_type")
        )
        return await super().create(payload)

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> RetentionClassDE | None:
        payload = dict(changes)
        if "resource_type" in payload:
            payload["resource_type"] = self.normalize_resource_type(
                payload.get("resource_type")
            )
        return await super().update(where, payload)

    async def _list_active_for_resource_type(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
    ) -> list[RetentionClassDE]:
        normalized = self.normalize_resource_type(resource_type)
        active_rows = await self.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "is_active": True,
                    }
                )
            ]
        )
        rows: list[RetentionClassDE] = []
        for row in active_rows:
            try:
                row_resource_type = self.normalize_resource_type(row.resource_type)
            except ValueError as exc:
                raise RetentionClassResolutionError(
                    "Encountered unsupported active retention class ResourceType."
                ) from exc
            if row_resource_type == normalized:
                rows.append(row)
        return rows

    async def resolve_active_for_resource_type(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
    ) -> RetentionClassDE | None:
        rows = await self._list_active_for_resource_type(
            tenant_id=tenant_id,
            resource_type=resource_type,
        )
        if len(rows) == 0:
            return None
        if len(rows) > 1:
            normalized = self.normalize_resource_type(resource_type)
            raise RetentionClassResolutionError(
                "Ambiguous active retention class state for "
                f"{tenant_id}/{normalized}."
            )
        return rows[0]
