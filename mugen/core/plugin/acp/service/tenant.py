"""Provides a service for the Tenant declarative model."""

__all__ = ["TenantService"]

import uuid
from typing import Any

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.service import ITenantService
from mugen.core.plugin.acp.domain import TenantDE


class TenantService(
    IRelationalService[TenantDE],
    ITenantService,
):
    """A service for the Tenant declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TenantDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

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
