"""Provides a CRUD service for vendors (plus lifecycle actions)."""

__all__ = ["VendorService"]

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict

from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.ops_vpn.contract.service.vendor import IVendorService
from mugen.core.plugin.ops_vpn.domain import VendorDE


class VendorService(
    IRelationalService[VendorDE],
    IVendorService,
):
    """A CRUD service for vendors."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VendorDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> VendorDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Vendor not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_status(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        from_statuses: set[str],
        to_status: str,
        changes: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status not in from_statuses:
            abort(
                409,
                f"Vendor can only transition to {to_status} from "
                f"{sorted(from_statuses)}.",
            )

        patch = {"status": to_status}
        patch.update(dict(changes or {}))

        svc: ICrudServiceWithRowVersion[VendorDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=patch,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204

    async def action_activate(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Activate a vendor."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        onboarding_completed_at = current.onboarding_completed_at
        if onboarding_completed_at is None:
            onboarding_completed_at = datetime.now(timezone.utc)

        return await self._update_status(
            where=where,
            expected_row_version=expected_row_version,
            from_statuses={"candidate", "suspended"},
            to_status="active",
            changes={"onboarding_completed_at": onboarding_completed_at},
        )

    async def action_suspend(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Suspend a vendor."""
        return await self._update_status(
            where=where,
            expected_row_version=int(data.row_version),
            from_statuses={"active"},
            to_status="suspended",
        )

    async def action_delist(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Delist a vendor."""
        return await self._update_status(
            where=where,
            expected_row_version=int(data.row_version),
            from_statuses={"candidate", "active", "suspended"},
            to_status="delisted",
        )

    async def action_reverify(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Record a vendor reverification timestamp and due date."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "delisted":
            abort(409, "Delisted vendors cannot be reverified.")

        now = datetime.now(timezone.utc)
        cadence_days = int(current.reverification_cadence_days or 365)
        if cadence_days <= 0:
            cadence_days = 365

        changes: dict[str, Any] = {
            "last_reverified_at": now,
            "next_reverification_due_at": now + timedelta(days=cadence_days),
        }

        if current.onboarding_completed_at is None and current.status == "candidate":
            changes["onboarding_completed_at"] = now

        svc: ICrudServiceWithRowVersion[VendorDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204
