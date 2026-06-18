"""Provides a service for the Tenant declarative model."""

__all__ = ["TenantService"]

import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.tenant_lifecycle import (
    tenant_lifecycle_contributors,
)
from mugen.core.plugin.acp.contract.service import ITenantService
from mugen.core.plugin.acp.domain import TenantDE
from mugen.core.plugin.acp.sdk.tenant_materialization import (
    materialize_tenant_role_templates,
)


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class TenantService(
    IRelationalService[TenantDE],
    ITenantService,
):
    """A service for the Tenant declarative model."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        registry_provider=_registry_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=TenantDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._registry_provider = registry_provider

    async def create(self, values: Mapping[str, Any]) -> TenantDE:
        """Create a tenant and run tenant-created provisioning hooks."""
        tenant = await super().create(values)
        contributors = tenant_lifecycle_contributors()
        registry: IAdminRegistry | None = self._registry_provider()

        if registry is None:
            raise RuntimeError("ACP registry is required for tenant provisioning.")

        if tenant.id is None:
            raise RuntimeError("Created tenant has no id.")

        await materialize_tenant_role_templates(
            tenant_id=tenant.id,
            registry=registry,
        )

        for contributor in contributors:
            await contributor.tenant_created(
                tenant=tenant,
                registry=registry,
            )

        return tenant

    async def _transition_status(
        self,
        *,
        entity_id: uuid.UUID,
        expected_row_version: int,
        from_status: str,
        to_status: str,
    ) -> tuple[dict[str, Any], int]:
        try:
            current = await self.get({"id": entity_id})
        except SQLAlchemyError:
            abort(500)

        if current is None:
            abort(404, "Tenant not found.")

        if current.status != from_status:
            abort(
                409,
                (
                    f"Tenant can only transition to {to_status} from "
                    f"{from_status}."
                ),
            )

        svc: ICrudServiceWithRowVersion[TenantDE] = self
        try:
            updated = await svc.update_with_row_version(
                {"id": entity_id},
                expected_row_version=expected_row_version,
                changes={"status": to_status},
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204

    async def entity_action_deactivate(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Deactivate a Tenant."""
        return await self._transition_status(
            entity_id=entity_id,
            expected_row_version=int(data.row_version),
            from_status="active",
            to_status="suspended",
        )

    async def entity_action_reactivate(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reactivate a Tenant."""
        return await self._transition_status(
            entity_id=entity_id,
            expected_row_version=int(data.row_version),
            from_status="suspended",
            to_status="active",
        )
