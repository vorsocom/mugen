"""Provides a CRUD service for billing invoices (plus common lifecycle actions)."""

__all__ = ["InvoiceService"]

import uuid
from datetime import datetime, timezone
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
from mugen.core.plugin.billing.contract.service.invoice import IInvoiceService
from mugen.core.plugin.billing.domain import InvoiceDE


class InvoiceService(
    IRelationalService[InvoiceDE],
    IInvoiceService,
):
    """A CRUD service for billing invoices."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=InvoiceDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> InvoiceDE:
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
            abort(404, "Invoice not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def action_issue(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Issue an invoice (draft -> issued)."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != "draft":
            abort(409, "Invoice can only be issued from draft status.")

        svc: ICrudServiceWithRowVersion[InvoiceDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "issued",
                    "issued_at": datetime.now(timezone.utc),
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204

    async def action_void(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Void an invoice."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status not in {"draft", "issued"}:
            abort(409, "Invoice can only be voided from draft or issued status.")

        svc: ICrudServiceWithRowVersion[InvoiceDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "void",
                    "voided_at": datetime.now(timezone.utc),
                    "amount_due": 0,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204

    async def action_mark_paid(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Mark an invoice as paid."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != "issued":
            abort(409, "Invoice can only be marked paid from issued status.")

        svc: ICrudServiceWithRowVersion[InvoiceDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "paid",
                    "paid_at": datetime.now(timezone.utc),
                    "amount_due": 0,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204
