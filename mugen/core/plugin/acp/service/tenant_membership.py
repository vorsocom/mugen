"""Provides a service for the TenantMembership declarative model."""

__all__ = ["TenantMembershipService"]

import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.service import ITenantMembershipService
from mugen.core.plugin.acp.domain import TenantMembershipDE


class TenantMembershipService(
    IRelationalService[TenantMembershipDE],
    ITenantMembershipService,
):
    """A service for the Tenant declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TenantMembershipDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _transition_status(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        from_statuses: set[str],
        to_status: str,
    ) -> tuple[dict[str, Any], int]:
        try:
            current = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if current is None:
            abort(404, "Tenant membership not found.")

        if current.status not in from_statuses:
            abort(
                409,
                (
                    f"TenantMembership can only transition to {to_status} from "
                    f"{sorted(from_statuses)}."
                ),
            )

        svc: ICrudServiceWithRowVersion[TenantMembershipDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
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

    async def action_suspend(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Suspend an active membership."""
        return await self._transition_status(
            where=where,
            expected_row_version=int(data.row_version),
            from_statuses={"active"},
            to_status="suspended",
        )

    async def action_unsuspend(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Unsuspend a suspended membership."""
        return await self._transition_status(
            where=where,
            expected_row_version=int(data.row_version),
            from_statuses={"suspended"},
            to_status="active",
        )

    async def action_remove(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Remove a membership."""
        svc: ICrudServiceWithRowVersion[TenantMembershipDE] = self
        try:
            deleted = await svc.delete_with_row_version(
                where=where,
                expected_row_version=int(data.row_version),
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if deleted is None:
            abort(404, "Delete not performed. No row matched.")

        return "", 204
