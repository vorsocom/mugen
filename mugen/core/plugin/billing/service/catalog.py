"""Provides services for global billing catalog definitions."""

from __future__ import annotations

__all__ = [
    "CurrencyDefinitionService",
    "DiscountDefinitionService",
    "InvoiceTemplateService",
    "MeterDefinitionService",
    "PaymentTermService",
    "PriceEntitlementService",
    "RunDefinitionService",
    "TaxCodeService",
    "TaxRateService",
]

from datetime import datetime, timezone
from typing import Any, Generic, Mapping, TypeVar
import uuid

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
)
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.billing.domain.catalog import (
    CurrencyDefinitionDE,
    DiscountDefinitionDE,
    InvoiceTemplateDE,
    MeterDefinitionDE,
    PaymentTermDE,
    PriceEntitlementDE,
    RunDefinitionDE,
    TaxCodeDE,
    TaxRateDE,
)

T = TypeVar("T")


class _GlobalDefinitionService(IRelationalService[T], Generic[T]):
    """Shared normalization, immutability, and activation behavior."""

    _semantic_fields: frozenset[str] = frozenset({"code"})
    _reference_fields: tuple[tuple[str, str], ...] = ()

    @staticmethod
    def _normalize_changes(values: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(values)
        for field_name in (
            "aggregation_mode",
            "code",
            "coupon_code",
            "frequency",
            "jurisdiction_code",
            "kind",
            "rollover_policy",
            "template_format",
            "unit",
        ):
            value = payload.get(field_name)
            if isinstance(value, str):
                payload[field_name] = value.strip().casefold()
        for field_name in (
            "body_template",
            "description",
            "display_name",
            "locale",
            "subject_template",
            "timezone",
        ):
            value = payload.get(field_name)
            if isinstance(value, str):
                payload[field_name] = value.strip()
        return payload

    async def _is_referenced(self, entity_id: uuid.UUID) -> bool:
        for table_name, field_name in self._reference_fields:
            count = await self._rsg.count_many(
                table_name,
                filter_groups=[FilterGroup(where={field_name: entity_id})],
            )
            if count:
                return True
        return False

    async def _validate_update(
        self,
        current: T,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = self._normalize_changes(changes)
        changed_semantics = {
            field_name
            for field_name in self._semantic_fields.intersection(payload)
            if payload[field_name] != getattr(current, field_name)
        }
        entity_id = getattr(current, "id", None)
        if changed_semantics and entity_id is not None:
            if await self._is_referenced(entity_id):
                abort(
                    409,
                    "Referenced global definitions cannot change semantic fields: "
                    + ", ".join(sorted(changed_semantics)),
                )
        return payload

    async def create(self, values: Mapping[str, Any]) -> T:
        return await super().create(self._normalize_changes(values))

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> T | None:
        current = await self.get(where)
        if current is None:
            return None
        payload = await self._validate_update(current, changes)
        return await super().update(where, payload)

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> T | None:
        current = await self.get(where)
        if current is None:
            return None
        payload = await self._validate_update(current, changes)
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=payload,
        )

    async def _get_for_action(
        self,
        *,
        entity_id: uuid.UUID,
        expected_row_version: int,
    ) -> T:
        where = {"id": entity_id}
        try:
            current = await self.get(
                {"id": entity_id, "row_version": expected_row_version}
            )
        except SQLAlchemyError:
            abort(500)
        if current is not None:
            return current
        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)
        if base is None:
            abort(404, "Global billing definition not found.")
        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _set_active(
        self,
        *,
        entity_id: uuid.UUID,
        expected_row_version: int,
        active: bool,
    ) -> tuple[dict[str, Any], int]:
        current = await self._get_for_action(
            entity_id=entity_id,
            expected_row_version=expected_row_version,
        )
        if bool(getattr(current, "is_active", False)) == active:
            return "", 204
        if not active and await self._is_referenced(entity_id):
            abort(409, "Definition cannot be deactivated while it is referenced.")
        try:
            updated = await super().update_with_row_version(
                {"id": entity_id},
                expected_row_version=expected_row_version,
                changes={"is_active": active},
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)
        if updated is None:
            abort(404, "Definition update was not performed.")
        return "", 204

    async def entity_action_activate(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Activate a global billing definition."""
        return await self._set_active(
            entity_id=entity_id,
            expected_row_version=int(data.row_version),
            active=True,
        )

    async def entity_action_deactivate(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Deactivate an unreferenced global billing definition."""
        return await self._set_active(
            entity_id=entity_id,
            expected_row_version=int(data.row_version),
            active=False,
        )


class MeterDefinitionService(_GlobalDefinitionService[MeterDefinitionDE]):
    """Manage canonical global meter definitions."""

    _semantic_fields = frozenset({"code", "unit", "aggregation_mode"})
    _reference_fields = (
        ("billing_price", "meter_definition_id"),
        ("billing_price_entitlement", "meter_definition_id"),
        ("billing_entitlement_bucket", "meter_definition_id"),
        ("billing_usage_event", "meter_definition_id"),
        ("ops_metering_meter_policy", "meter_definition_id"),
        ("ops_metering_usage_session", "meter_definition_id"),
        ("ops_metering_usage_record", "meter_definition_id"),
        ("ops_metering_rated_usage", "meter_definition_id"),
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=MeterDefinitionDE, table=table, rsg=rsg, **kwargs)


class PriceEntitlementService(_GlobalDefinitionService[PriceEntitlementDE]):
    """Manage structured Price entitlement rules."""

    _semantic_fields = frozenset(
        {"price_id", "meter_definition_id", "included_quantity", "rollover_policy"}
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=PriceEntitlementDE, table=table, rsg=rsg, **kwargs)

    async def _price_was_used(self, price_id: uuid.UUID) -> bool:
        count = await self._rsg.count_many(
            "billing_subscription",
            filter_groups=[FilterGroup(where={"price_id": price_id})],
        )
        return count > 0

    async def _validate_contract(self, payload: Mapping[str, Any]) -> None:
        price = await self._rsg.get_one(
            "billing_price",
            {"id": payload["price_id"]},
        )
        if price is None or price.get("deleted_at") is not None:
            abort(409, "Price entitlement requires an active Price.")
        if price.get("price_type") != "recurring":
            abort(409, "Price entitlement requires a recurring package Price.")
        if not price.get("interval_unit") or not price.get("interval_count"):
            abort(409, "Recurring package Price requires a complete interval.")
        meter = await self._rsg.get_one(
            "billing_meter_definition",
            {"id": payload["meter_definition_id"]},
        )
        if meter is None or not meter.get("is_active"):
            abort(409, "Price entitlement requires an active meter definition.")

    async def create(self, values: Mapping[str, Any]) -> PriceEntitlementDE:
        payload = self._normalize_changes(values)
        await self._validate_contract(payload)
        if await self._price_was_used(payload["price_id"]):
            abort(409, "Used Prices cannot acquire or change entitlement rules.")
        return await IRelationalService.create(self, payload)

    async def _validate_update(
        self,
        current: PriceEntitlementDE,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = self._normalize_changes(changes)
        if current.price_id is None:
            abort(409, "Price entitlement has no Price provenance.")
        if await self._price_was_used(current.price_id):
            abort(409, "Entitlement rules are immutable after Subscription use.")
        effective = {
            "price_id": current.price_id,
            "meter_definition_id": current.meter_definition_id,
        }
        effective.update(payload)
        await self._validate_contract(effective)
        return payload

    async def entity_action_archive(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Archive an unused Price entitlement rule."""
        current = await self._get_for_action(
            entity_id=entity_id,
            expected_row_version=int(data.row_version),
        )
        if current.deleted_at is not None:
            return "", 204
        if current.price_id is None or await self._price_was_used(current.price_id):
            abort(409, "Entitlement rules are immutable after Subscription use.")
        try:
            updated = await IRelationalService.update_with_row_version(
                self,
                {"id": entity_id},
                expected_row_version=int(data.row_version),
                changes={
                    "deleted_at": datetime.now(timezone.utc),
                    "deleted_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        if updated is None:
            abort(404, "Archive not performed.")
        return "", 204


class RunDefinitionService(_GlobalDefinitionService[RunDefinitionDE]):
    """Manage reusable billing-run definitions."""

    _semantic_fields = frozenset({"code", "frequency", "interval_count", "timezone"})
    _reference_fields = (
        ("billing_subscription", "run_definition_id"),
        ("billing_run", "definition_id"),
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=RunDefinitionDE, table=table, rsg=rsg, **kwargs)


class CurrencyDefinitionService(_GlobalDefinitionService[CurrencyDefinitionDE]):
    """Activate or deactivate immutable vendored ISO currency definitions."""

    _semantic_fields = frozenset({"code", "numeric_code", "minor_unit"})
    _reference_fields = (
        ("billing_price", "currency_definition_id"),
        ("billing_account", "currency_definition_id"),
        ("billing_invoice", "currency_definition_id"),
        ("billing_payment", "currency_definition_id"),
        ("billing_credit_note", "currency_definition_id"),
        ("billing_adjustment", "currency_definition_id"),
        ("billing_ledger_entry", "currency_definition_id"),
        ("billing_discount_definition", "currency_definition_id"),
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=CurrencyDefinitionDE, table=table, rsg=rsg, **kwargs)


class TaxCodeService(_GlobalDefinitionService[TaxCodeDE]):
    """Manage reusable global tax codes."""

    _reference_fields = (
        ("billing_tax_rate", "tax_code_id"),
        ("billing_account", "tax_code_id"),
        ("billing_subscription", "tax_code_id"),
        ("billing_invoice", "tax_code_id"),
        ("billing_invoice_line", "tax_code_id"),
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=TaxCodeDE, table=table, rsg=rsg, **kwargs)


class TaxRateService(_GlobalDefinitionService[TaxRateDE]):
    """Manage non-overlapping, effective-dated global tax rates."""

    _semantic_fields = frozenset(
        {
            "code",
            "tax_code_id",
            "jurisdiction_code",
            "rate_basis_points",
            "effective_from",
            "effective_to",
        }
    )
    _reference_fields = (("billing_invoice_line", "tax_rate_id"),)

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=TaxRateDE, table=table, rsg=rsg, **kwargs)

    async def _validate_tax_rate(
        self,
        payload: Mapping[str, Any],
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        tax_code = await self._rsg.get_one(
            "billing_tax_code",
            {"id": payload["tax_code_id"]},
        )
        if tax_code is None or not tax_code.get("is_active"):
            abort(409, "Tax Rate requires an active Tax Code.")
        candidates = await self.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tax_code_id": payload["tax_code_id"],
                        "jurisdiction_code": payload["jurisdiction_code"],
                        "is_active": True,
                    }
                )
            ]
        )
        start = payload["effective_from"]
        end = payload.get("effective_to")
        for candidate in candidates:
            if candidate.id == exclude_id:
                continue
            candidate_start = candidate.effective_from
            candidate_end = candidate.effective_to
            if candidate_start is None:
                continue
            if (end is None or candidate_start < end) and (
                candidate_end is None or start < candidate_end
            ):
                abort(409, "Tax Rate effective period overlaps an active rate.")

    async def create(self, values: Mapping[str, Any]) -> TaxRateDE:
        payload = self._normalize_changes(values)
        await self._validate_tax_rate(payload)
        return await IRelationalService.create(self, payload)

    async def _validate_update(
        self,
        current: TaxRateDE,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = await super()._validate_update(current, changes)
        effective = {
            "tax_code_id": current.tax_code_id,
            "jurisdiction_code": current.jurisdiction_code,
            "effective_from": current.effective_from,
            "effective_to": current.effective_to,
        }
        effective.update(payload)
        await self._validate_tax_rate(effective, exclude_id=current.id)
        return payload


class PaymentTermService(_GlobalDefinitionService[PaymentTermDE]):
    """Manage reusable global payment terms."""

    _semantic_fields = frozenset({"code", "due_days"})
    _reference_fields = (
        ("billing_account", "payment_term_id"),
        ("billing_subscription", "payment_term_id"),
        ("billing_invoice", "payment_term_id"),
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=PaymentTermDE, table=table, rsg=rsg, **kwargs)


class InvoiceTemplateService(_GlobalDefinitionService[InvoiceTemplateDE]):
    """Manage reusable global invoice templates."""

    _semantic_fields = frozenset(
        {"code", "locale", "template_format", "subject_template", "body_template"}
    )
    _reference_fields = (
        ("billing_account", "invoice_template_id"),
        ("billing_subscription", "invoice_template_id"),
        ("billing_invoice", "invoice_template_id"),
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=InvoiceTemplateDE, table=table, rsg=rsg, **kwargs)


class DiscountDefinitionService(_GlobalDefinitionService[DiscountDefinitionDE]):
    """Manage reusable global discount definitions."""

    _semantic_fields = frozenset(
        {
            "code",
            "kind",
            "percentage_basis_points",
            "amount",
            "currency_definition_id",
        }
    )
    _reference_fields = (
        ("billing_account", "discount_definition_id"),
        ("billing_subscription", "discount_definition_id"),
        ("billing_invoice", "discount_definition_id"),
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=DiscountDefinitionDE, table=table, rsg=rsg, **kwargs)

    async def create(self, values: Mapping[str, Any]) -> DiscountDefinitionDE:
        payload = self._normalize_changes(values)
        currency_id = payload.get("currency_definition_id")
        if currency_id is not None:
            currency = await self._rsg.get_one(
                "billing_currency_definition",
                {"id": currency_id},
            )
            if currency is None or not currency.get("is_active"):
                abort(409, "Fixed discount requires an active currency.")
        return await IRelationalService.create(self, payload)
