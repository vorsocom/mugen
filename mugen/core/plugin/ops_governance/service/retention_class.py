"""Provides a CRUD service for retention classes."""

__all__ = ["RetentionClassResolutionError", "RetentionClassService"]

import uuid

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.plugin.ops_governance.contract.service.retention_class import (
    IRetentionClassService,
)
from mugen.core.plugin.ops_governance.domain import RetentionClassDE


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
        text = str(value or "").strip().lower().replace("-", "_")
        if text in {"audit_event", "auditevent", "audit"}:
            return "audit_event"
        if text in {"evidence_blob", "evidenceblob", "evidence"}:
            return "evidence_blob"
        raise ValueError(f"Unsupported resource type: {value!r}.")

    async def _list_active_for_resource_type(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
    ) -> list[RetentionClassDE]:
        normalized = self.normalize_resource_type(resource_type)
        rows = await self.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "resource_type": normalized,
                        "is_active": True,
                    }
                )
            ]
        )
        return list(rows)

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
