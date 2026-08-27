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
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict

from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.billing.contract.service.invoice import IInvoiceService
from mugen.core.plugin.billing.domain import InvoiceDE
from mugen.core.plugin.billing.service.reference import BillingReferenceService


class InvoiceService(
    BillingReferenceService[InvoiceDE],
    IInvoiceService,
):
    """A CRUD service for billing invoices."""

    _currency_snapshot = True
    _active_reference_tables = {
        "currency_definition_id": (
            "billing_currency_definition",
            "CurrencyDefinitionId",
        ),
        "tax_code_id": ("billing_tax_code", "TaxCodeId"),
        "payment_term_id": ("billing_payment_term", "PaymentTermId"),
        "invoice_template_id": ("billing_invoice_template", "InvoiceTemplateId"),
        "discount_definition_id": (
            "billing_discount_definition",
            "DiscountDefinitionId",
        ),
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=InvoiceDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def create(self, values: Mapping[str, Any]) -> InvoiceDE:
        payload = dict(values)
        tenant_id = payload["tenant_id"]
        account = await self._rsg.get_one(
            "billing_account",
            {
                "tenant_id": tenant_id,
                "id": payload["account_id"],
                "deleted_at": None,
            },
        )
        if account is None:
            abort(400, "AccountId must reference an available account in the tenant.")

        subscription = None
        if payload.get("subscription_id") is not None:
            subscription = await self._rsg.get_one(
                "billing_subscription",
                {"tenant_id": tenant_id, "id": payload["subscription_id"]},
            )
            if subscription is None or subscription.get("account_id") != account["id"]:
                abort(400, "SubscriptionId must belong to the selected account.")

        if payload.get("billing_run_id") is not None:
            billing_run = await self._rsg.get_one(
                "billing_run",
                {"tenant_id": tenant_id, "id": payload["billing_run_id"]},
            )
            if billing_run is None:
                abort(400, "BillingRunId must reference a run in the route tenant.")
            if billing_run.get("account_id") not in (None, account["id"]):
                abort(400, "BillingRunId does not include the selected account.")
            if subscription is not None and billing_run.get("subscription_id") not in (
                None,
                subscription["id"],
            ):
                abort(400, "BillingRunId does not include the selected Subscription.")

        for field_name in (
            "tax_code_id",
            "payment_term_id",
            "invoice_template_id",
            "discount_definition_id",
        ):
            if payload.get(field_name) is None:
                if (
                    subscription is not None
                    and subscription.get(field_name) is not None
                ):
                    payload[field_name] = subscription[field_name]
                elif account.get(field_name) is not None:
                    payload[field_name] = account[field_name]

        price = None
        if subscription is not None:
            price = await self._rsg.get_one(
                "billing_price",
                {"id": subscription["price_id"]},
            )
            if price is None:
                abort(409, "Subscription Price is unavailable for invoicing.")
        expected_currency_id = (
            price.get("currency_definition_id") if price is not None else None
        )
        if payload.get("currency_definition_id") is None:
            payload["currency_definition_id"] = expected_currency_id or account.get(
                "currency_definition_id"
            )
        if payload.get("currency_definition_id") is None:
            abort(
                400,
                "CurrencyDefinitionId is required when no Subscription or Account "
                "currency default exists.",
            )
        if (
            expected_currency_id is not None
            and payload["currency_definition_id"] != expected_currency_id
        ):
            abort(409, "Invoice currency must match its Subscription Price.")

        return await super().create(payload)

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
