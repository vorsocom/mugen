"""Provides a service for the Role declarative model."""

__all__ = ["RoleService"]

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
from mugen.core.plugin.acp.contract.service import IRoleService
from mugen.core.plugin.acp.domain import RoleDE


class RoleService(
    IRelationalService[RoleDE],
    IRoleService,
):
    """A service for the Role declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=RoleDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _transition_status(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        from_status: str,
        to_status: str,
    ) -> tuple[dict[str, Any], int]:
        try:
            current = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if current is None:
            abort(404, "Role not found.")

        if current.status != from_status:
            abort(
                409,
                (
                    f"Role can only transition to {to_status} from "
                    f"{from_status}."
                ),
            )

        svc: ICrudServiceWithRowVersion[RoleDE] = self
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

    async def action_deprecate(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Deprecate an active tenant role."""
        return await self._transition_status(
            where=where,
            expected_row_version=int(data.row_version),
            from_status="active",
            to_status="deprecated",
        )

    async def action_reactivate(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reactivate a deprecated tenant role."""
        return await self._transition_status(
            where=where,
            expected_row_version=int(data.row_version),
            from_status="deprecated",
            to_status="active",
        )
