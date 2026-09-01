"""Provides Service Profile ingress assignment validation and CRUD."""

from __future__ import annotations

__all__ = ["ServiceProfileIngressBindingService"]

from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.service_profile.contract.service import (
    IServiceProfileIngressBindingService,
)
from mugen.core.plugin.service_profile.domain import ServiceProfileIngressBindingDE


class ServiceProfileIngressBindingService(
    IRelationalService[ServiceProfileIngressBindingDE],
    IServiceProfileIngressBindingService,
):
    """Validate exact tenant-scoped ingress assignments."""

    _PROFILE_TABLE = "service_profile_service_profile"
    _INGRESS_TABLE = "channel_orchestration_ingress_binding"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ServiceProfileIngressBindingDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _validate_references(self, values: Mapping[str, Any]) -> None:
        tenant_id = values.get("tenant_id")
        try:
            profile = await self._rsg.get_one(
                self._PROFILE_TABLE,
                {
                    "tenant_id": tenant_id,
                    "id": values.get("service_profile_id"),
                    "deleted_at": None,
                },
            )
            binding = await self._rsg.get_one(
                self._INGRESS_TABLE,
                {
                    "tenant_id": tenant_id,
                    "id": values.get("ingress_binding_id"),
                    "is_active": True,
                },
            )
        except SQLAlchemyError:
            abort(500)
        if profile is None or profile.get("status") == "disabled":
            abort(
                400,
                "ServiceProfileId must reference an available route-tenant profile.",
            )
        if binding is None:
            abort(
                400, "IngressBindingId must reference an active route-tenant binding."
            )

    async def create(
        self,
        values: Mapping[str, Any],
    ) -> ServiceProfileIngressBindingDE:
        """Create an assignment after validating both tenant-owned references."""
        payload = dict(values)
        payload.setdefault("is_active", True)
        await self._validate_references(payload)
        return await super().create(payload)

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> ServiceProfileIngressBindingDE | None:
        """Revalidate live references when an assignment is reactivated."""
        if changes.get("is_active") is True:
            current = await self.get(where)
            if current is None:
                return None
            await self._validate_references(
                {
                    "tenant_id": current.tenant_id,
                    "service_profile_id": current.service_profile_id,
                    "ingress_binding_id": current.ingress_binding_id,
                }
            )
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=changes,
        )
