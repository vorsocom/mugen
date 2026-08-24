"""Validation schemas used by billing ACP CRUD resources."""

from typing import Any
import uuid

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation,
    build_update_validation,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase

__all__ = [
    "BillingAccountCreateValidation",
    "BillingAccountUpdateValidation",
    "BillingAdjustmentCreateValidation",
    "BillingAdjustmentUpdateValidation",
    "BillingCreditNoteCreateValidation",
    "BillingCreditNoteUpdateValidation",
    "BillingEntitlementBucketCreateValidation",
    "BillingEntitlementBucketUpdateValidation",
    "BillingInvoiceCreateValidation",
    "BillingInvoiceLineCreateValidation",
    "BillingInvoiceLineUpdateValidation",
    "BillingInvoiceUpdateValidation",
    "BillingLedgerEntryCreateValidation",
    "BillingPaymentAllocationCreateValidation",
    "BillingPaymentCreateValidation",
    "BillingPaymentUpdateValidation",
    "BillingPriceCreateValidation",
    "BillingPriceUpdateValidation",
    "BillingProductCreateValidation",
    "BillingProductUpdateValidation",
    "BillingRunCreateValidation",
    "BillingRunUpdateValidation",
    "BillingSubscriptionCreateValidation",
    "BillingSubscriptionUpdateValidation",
    "BillingUsageAllocationCreateValidation",
    "BillingUsageEventCreateValidation",
]


BillingAccountCreateValidation = build_create_validation(
    "BillingAccountCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingAccount.",
    required_uuid=("tenant_id",),
    required_text=("code", "display_name"),
)

BillingAccountUpdateValidation = build_update_validation(
    "BillingAccountUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingAccount.",
    optional_text=("code", "display_name", "email", "external_ref"),
    optional_any=("attributes",),
)


class _GlobalCatalogValidation(IValidationBase):
    """Reject tenant ownership fields on global catalog payloads."""

    @model_validator(mode="before")
    @classmethod
    def _reject_tenant_id(cls, value: Any) -> Any:
        if isinstance(value, dict) and ("TenantId" in value or "tenant_id" in value):
            raise ValueError("TenantId is not valid for global catalog resources.")
        return value

    @staticmethod
    def _required_text(value: str | None, field_name: str) -> str:
        if value is None:
            raise ValueError(f"{field_name} must not be null.")
        normalized = str(value).strip()
        if normalized == "":
            raise ValueError(f"{field_name} must be non-empty.")
        return normalized

    @staticmethod
    def _optional_text(value: str | None, field_name: str) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if normalized == "":
            raise ValueError(f"{field_name} must be non-empty when provided.")
        return normalized


class BillingProductCreateValidation(_GlobalCatalogValidation):
    """Validate create payloads for a global BillingProduct."""

    code: str
    name: str
    description: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingProductCreateValidation":
        self.code = self._required_text(self.code, "Code")
        self.name = self._required_text(self.name, "Name")
        self.description = self._optional_text(self.description, "Description")
        return self


class BillingProductUpdateValidation(_GlobalCatalogValidation):
    """Validate update payloads for a global BillingProduct."""

    code: str | None = None
    name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingProductUpdateValidation":
        mutable = {"code", "name", "description", "attributes"}
        if not mutable.intersection(self.model_fields_set):
            raise ValueError("At least one mutable field must be provided.")
        if "code" in self.model_fields_set:
            self.code = self._required_text(self.code, "Code")
        if "name" in self.model_fields_set:
            self.name = self._required_text(self.name, "Name")
        self.description = self._optional_text(self.description, "Description")
        return self


class BillingPriceCreateValidation(_GlobalCatalogValidation):
    """Validate create payloads for a global BillingPrice."""

    product_id: uuid.UUID
    code: str
    price_type: str
    currency: str
    unit_amount: NonNegativeInt | None = None
    interval_unit: str | None = None
    interval_count: PositiveInt | None = None
    trial_period_days: NonNegativeInt | None = None
    usage_unit: str | None = None
    meter_code: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize_and_validate_meter(self) -> "BillingPriceCreateValidation":
        self.code = self._required_text(self.code, "Code")
        self.price_type = self._required_text(
            self.price_type,
            "PriceType",
        ).lower()
        self.currency = self._required_text(self.currency, "Currency").upper()
        self.interval_unit = self._optional_text(
            self.interval_unit,
            "IntervalUnit",
        )
        if self.interval_unit is not None:
            self.interval_unit = self.interval_unit.lower()
        self.usage_unit = self._optional_text(self.usage_unit, "UsageUnit")
        self.meter_code = self._optional_text(self.meter_code, "MeterCode")

        has_meter_code = self.meter_code is not None
        has_usage_unit = self.usage_unit is not None
        if has_meter_code != has_usage_unit:
            raise ValueError("MeterCode and UsageUnit must be provided together.")
        if self.price_type == "metered" and not has_meter_code:
            raise ValueError("Metered Prices require MeterCode and UsageUnit.")
        return self


class BillingPriceUpdateValidation(_GlobalCatalogValidation):
    """Validate update payloads for a global BillingPrice."""

    product_id: uuid.UUID | None = None
    code: str | None = None
    price_type: str | None = None
    currency: str | None = None
    unit_amount: NonNegativeInt | None = None
    interval_unit: str | None = None
    interval_count: PositiveInt | None = None
    trial_period_days: NonNegativeInt | None = None
    usage_unit: str | None = None
    meter_code: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingPriceUpdateValidation":
        mutable = {
            "product_id",
            "code",
            "price_type",
            "currency",
            "unit_amount",
            "interval_unit",
            "interval_count",
            "trial_period_days",
            "usage_unit",
            "meter_code",
            "attributes",
        }
        if not mutable.intersection(self.model_fields_set):
            raise ValueError("At least one mutable field must be provided.")

        if "product_id" in self.model_fields_set and self.product_id is None:
            raise ValueError("ProductId must not be null.")
        if "code" in self.model_fields_set:
            self.code = self._required_text(self.code, "Code")
        if "price_type" in self.model_fields_set:
            self.price_type = self._required_text(self.price_type, "PriceType")
        if self.price_type is not None:
            self.price_type = self.price_type.lower()
        if "currency" in self.model_fields_set:
            self.currency = self._required_text(self.currency, "Currency")
        if self.currency is not None:
            self.currency = self.currency.upper()
        self.interval_unit = self._optional_text(
            self.interval_unit,
            "IntervalUnit",
        )
        if self.interval_unit is not None:
            self.interval_unit = self.interval_unit.lower()
        self.usage_unit = self._optional_text(self.usage_unit, "UsageUnit")
        self.meter_code = self._optional_text(self.meter_code, "MeterCode")
        return self


BillingSubscriptionCreateValidation = build_create_validation(
    "BillingSubscriptionCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingSubscription.",
    required_uuid=("tenant_id", "account_id", "price_id"),
)

BillingSubscriptionUpdateValidation = build_update_validation(
    "BillingSubscriptionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingSubscription.",
    optional_text=("external_ref",),
    optional_datetime=(
        "current_period_start",
        "current_period_end",
        "cancel_at",
    ),
    optional_any=("attributes",),
)

BillingRunCreateValidation = build_create_validation(
    "BillingRunCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingRun.",
    required_uuid=("tenant_id",),
    required_text=("run_type", "idempotency_key"),
    required_datetime=("period_start", "period_end"),
)

BillingRunUpdateValidation = build_update_validation(
    "BillingRunUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingRun.",
    optional_uuid=("account_id", "subscription_id"),
    optional_text=("status", "external_ref", "error_message"),
    optional_datetime=("started_at", "finished_at"),
    optional_any=("attributes",),
)

BillingUsageEventCreateValidation = build_create_validation(
    "BillingUsageEventCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingUsageEvent.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("meter_code",),
    required_any=("quantity",),
)

BillingEntitlementBucketCreateValidation = build_create_validation(
    "BillingEntitlementBucketCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingEntitlementBucket.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("meter_code",),
    required_datetime=("period_start", "period_end"),
    required_any=("included_quantity",),
)

BillingEntitlementBucketUpdateValidation = build_update_validation(
    "BillingEntitlementBucketUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingEntitlementBucket.",
    optional_uuid=("subscription_id", "price_id"),
    optional_text=("meter_code", "external_ref"),
    optional_datetime=("period_start", "period_end"),
    optional_any=(
        "included_quantity",
        "rollover_quantity",
        "attributes",
    ),
)

BillingUsageAllocationCreateValidation = build_create_validation(
    "BillingUsageAllocationCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingUsageAllocation.",
    required_uuid=("tenant_id", "usage_event_id", "entitlement_bucket_id"),
    required_any=("allocated_quantity",),
)

BillingInvoiceCreateValidation = build_create_validation(
    "BillingInvoiceCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingInvoice.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("currency",),
)

BillingInvoiceUpdateValidation = build_update_validation(
    "BillingInvoiceUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingInvoice.",
    optional_uuid=("account_id", "subscription_id"),
    optional_text=("number", "currency"),
    optional_datetime=("due_at",),
    optional_any=(
        "subtotal_amount",
        "tax_amount",
        "total_amount",
        "attributes",
    ),
)

BillingCreditNoteCreateValidation = build_create_validation(
    "BillingCreditNoteCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingCreditNote.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("currency",),
)

BillingCreditNoteUpdateValidation = build_update_validation(
    "BillingCreditNoteUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingCreditNote.",
    optional_uuid=("invoice_id",),
    optional_text=("status", "number", "currency", "external_ref"),
    optional_datetime=("issued_at", "voided_at"),
    optional_any=("total_amount", "attributes"),
)

BillingAdjustmentCreateValidation = build_create_validation(
    "BillingAdjustmentCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingAdjustment.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("kind", "currency"),
    required_any=("amount",),
)

BillingAdjustmentUpdateValidation = build_update_validation(
    "BillingAdjustmentUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingAdjustment.",
    optional_uuid=("invoice_id", "credit_note_id"),
    optional_text=("reason", "external_ref"),
    optional_datetime=("occurred_at",),
    optional_any=("attributes",),
)

BillingInvoiceLineCreateValidation = build_create_validation(
    "BillingInvoiceLineCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingInvoiceLine.",
    required_uuid=("tenant_id", "invoice_id"),
    required_any=("quantity", "amount"),
)

BillingInvoiceLineUpdateValidation = build_update_validation(
    "BillingInvoiceLineUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingInvoiceLine.",
    optional_uuid=("price_id",),
    optional_text=("description",),
    optional_datetime=("period_start", "period_end"),
    optional_any=("quantity", "unit_amount", "amount", "attributes"),
)

BillingPaymentCreateValidation = build_create_validation(
    "BillingPaymentCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingPayment.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("currency",),
    required_any=("amount",),
)

BillingPaymentUpdateValidation = build_update_validation(
    "BillingPaymentUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingPayment.",
    optional_uuid=("invoice_id",),
    optional_text=("status", "currency", "provider", "external_ref"),
    optional_datetime=("received_at", "failed_at"),
    optional_any=("amount", "attributes"),
)

BillingPaymentAllocationCreateValidation = build_create_validation(
    "BillingPaymentAllocationCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingPaymentAllocation.",
    required_uuid=("tenant_id", "payment_id", "invoice_id"),
    required_any=("amount",),
)

BillingLedgerEntryCreateValidation = build_create_validation(
    "BillingLedgerEntryCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingLedgerEntry.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("direction", "currency"),
    required_any=("amount",),
)
