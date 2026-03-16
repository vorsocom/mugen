"""Provides a CRUD service for billing payment allocations."""

__all__ = ["PaymentAllocationService"]

import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation

from mugen.core.plugin.billing.contract.service.payment_allocation import (
    IPaymentAllocationService,
)
from mugen.core.plugin.billing.domain import PaymentAllocationDE


class PaymentAllocationService(  # pylint: disable=too-few-public-methods
    IRelationalService[PaymentAllocationDE],
    IPaymentAllocationService,
):
    """A CRUD service for billing payment allocations."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PaymentAllocationDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> PaymentAllocationDE:
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
            abort(404, "Payment allocation not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _sync_invoice_from_allocations(
        self,
        *,
        tenant_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> None:
        raw_session = getattr(self._rsg, "raw_session", None)
        if raw_session is None or not callable(raw_session):
            abort(500, "Invoice sync function requires raw SQL session support.")

        async with raw_session() as session:
            await session.execute(
                sa_text(
                    """
                    SELECT mugen.fn_billing_sync_invoice_from_allocations(
                        :tenant_id,
                        :invoice_id
                    );
                    """
                ),
                {"tenant_id": tenant_id, "invoice_id": invoice_id},
            )

    async def action_sync_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Recompute the linked invoice amount due and status from allocations."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.invoice_id is None:
            abort(409, "Payment allocation does not reference an invoice.")

        try:
            await self._sync_invoice_from_allocations(
                tenant_id=tenant_id,
                invoice_id=current.invoice_id,
            )
        except SQLAlchemyError:
            abort(500)

        return "", 204
