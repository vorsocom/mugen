"""Validation schemas used by billing ACP CRUD resources."""

from datetime import datetime
from typing import Any
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict, NonNegativeInt, PositiveInt, model_validator

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
    "BillingDiscountDefinitionCreateValidation",
    "BillingDiscountDefinitionUpdateValidation",
    "BillingEntitlementAdjustValidation",
    "BillingEntitlementBucketCreateValidation",
    "BillingEntitlementBucketUpdateValidation",
    "BillingInvoiceTemplateCreateValidation",
    "BillingInvoiceTemplateUpdateValidation",
    "BillingInvoiceCreateValidation",
    "BillingInvoiceLineCreateValidation",
    "BillingInvoiceLineUpdateValidation",
    "BillingInvoiceUpdateValidation",
    "BillingLedgerEntryCreateValidation",
    "BillingMeterDefinitionCreateValidation",
    "BillingMeterDefinitionUpdateValidation",
    "BillingPaymentAllocationCreateValidation",
    "BillingPaymentCreateValidation",
    "BillingPaymentTermCreateValidation",
    "BillingPaymentTermUpdateValidation",
    "BillingPaymentUpdateValidation",
    "BillingPriceCreateValidation",
    "BillingPriceEntitlementCreateValidation",
    "BillingPriceEntitlementUpdateValidation",
    "BillingPriceUpdateValidation",
    "BillingProductCreateValidation",
    "BillingProductUpdateValidation",
    "BillingRunCreateValidation",
    "BillingRunDefinitionCreateValidation",
    "BillingRunDefinitionUpdateValidation",
    "BillingRunFailValidation",
    "BillingRunRetryValidation",
    "BillingRunUpdateValidation",
    "BillingSubscriptionCreateValidation",
    "BillingSubscriptionPeriodValidation",
    "BillingSubscriptionUpdateValidation",
    "BillingTaxCodeCreateValidation",
    "BillingTaxCodeUpdateValidation",
    "BillingTaxRateCreateValidation",
    "BillingTaxRateUpdateValidation",
    "BillingUsageAllocationCreateValidation",
    "BillingUsageEventCreateValidation",
]


def _require_aware_datetime(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must include a UTC offset.")


BillingAccountCreateValidation = build_create_validation(
    "BillingAccountCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingAccount.",
    required_uuid=("tenant_id",),
    required_text=("code", "display_name"),
    optional_uuid=(
        "currency_definition_id",
        "tax_code_id",
        "payment_term_id",
        "invoice_template_id",
        "discount_definition_id",
    ),
)

BillingAccountUpdateValidation = build_update_validation(
    "BillingAccountUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingAccount.",
    optional_text=("code", "display_name", "email", "external_ref"),
    optional_uuid=(
        "currency_definition_id",
        "tax_code_id",
        "payment_term_id",
        "invoice_template_id",
        "discount_definition_id",
    ),
    optional_any=("attributes",),
)


class _GlobalCatalogValidation(IValidationBase):
    """Reject tenant ownership fields on global catalog payloads."""

    model_config = ConfigDict(
        alias_generator=IValidationBase.model_config.get("alias_generator"),
        populate_by_name=True,
        extra="forbid",
    )

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

    @staticmethod
    def _normalize_attributes(value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        forbidden_keys = {
            "accountid",
            "bankaccount",
            "cardnumber",
            "contact",
            "credential",
            "customerid",
            "email",
            "financialtransaction",
            "paymentmethod",
            "phone",
            "secret",
            "tenantid",
            "token",
        }
        unsafe: list[str] = []

        def walk(item: Any, path: str) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    label = str(key).strip()
                    normalized = "".join(
                        char for char in label.casefold() if char.isalnum()
                    )
                    child_path = f"{path}.{label}" if path else label
                    if normalized in forbidden_keys or any(
                        fragment in normalized
                        for fragment in ("credential", "secret", "token")
                    ):
                        unsafe.append(child_path)
                    walk(child, child_path)
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    walk(child, f"{path}[{index}]")

        walk(value, "")
        if unsafe:
            raise ValueError(
                "Attributes contain tenant/customer-sensitive keys: "
                + ", ".join(sorted(unsafe))
            )
        return value


class _NamedDefinitionValidation(_GlobalCatalogValidation):
    """Shared fields for named global billing definitions."""

    code: str
    display_name: str
    description: str | None = None
    attributes: dict[str, Any] | None = None

    def _normalize_definition(self) -> None:
        self.code = self._required_text(self.code, "Code").casefold()
        self.display_name = self._required_text(self.display_name, "DisplayName")
        self.description = self._optional_text(self.description, "Description")
        self.attributes = self._normalize_attributes(self.attributes)


class _NamedDefinitionUpdateValidation(_GlobalCatalogValidation):
    """Shared mutable fields for named global billing definitions."""

    code: str | None = None
    display_name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None

    def _normalize_definition_update(
        self, extra_fields: set[str] | None = None
    ) -> None:
        mutable = {"code", "display_name", "description", "attributes"}
        mutable.update(extra_fields or set())
        if not mutable.intersection(self.model_fields_set):
            raise ValueError("At least one mutable field must be provided.")
        if "code" in self.model_fields_set:
            self.code = self._required_text(self.code, "Code").casefold()
        if "display_name" in self.model_fields_set:
            self.display_name = self._required_text(self.display_name, "DisplayName")
        if "description" in self.model_fields_set:
            self.description = self._optional_text(self.description, "Description")
        if "attributes" in self.model_fields_set:
            self.attributes = self._normalize_attributes(self.attributes)


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
        self.attributes = self._normalize_attributes(self.attributes)
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
        if "description" in self.model_fields_set:
            self.description = self._optional_text(self.description, "Description")
        if "attributes" in self.model_fields_set:
            self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingPriceCreateValidation(_GlobalCatalogValidation):
    """Validate create payloads for a global BillingPrice."""

    product_id: uuid.UUID
    code: str
    price_type: str
    currency_definition_id: uuid.UUID
    meter_definition_id: uuid.UUID | None = None
    unit_amount: NonNegativeInt | None = None
    interval_unit: str | None = None
    interval_count: PositiveInt | None = None
    trial_period_days: NonNegativeInt | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize_and_validate_meter(self) -> "BillingPriceCreateValidation":
        self.code = self._required_text(self.code, "Code")
        self.price_type = self._required_text(
            self.price_type,
            "PriceType",
        ).lower()
        self.interval_unit = self._optional_text(
            self.interval_unit,
            "IntervalUnit",
        )
        if self.interval_unit is not None:
            self.interval_unit = self.interval_unit.lower()
        if self.price_type == "metered" and self.meter_definition_id is None:
            raise ValueError("Metered Prices require MeterDefinitionId.")
        if self.price_type != "metered" and self.meter_definition_id is not None:
            raise ValueError("Unmetered Prices must omit MeterDefinitionId.")
        self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingPriceUpdateValidation(_GlobalCatalogValidation):
    """Validate update payloads for a global BillingPrice."""

    product_id: uuid.UUID | None = None
    code: str | None = None
    price_type: str | None = None
    currency_definition_id: uuid.UUID | None = None
    meter_definition_id: uuid.UUID | None = None
    unit_amount: NonNegativeInt | None = None
    interval_unit: str | None = None
    interval_count: PositiveInt | None = None
    trial_period_days: NonNegativeInt | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingPriceUpdateValidation":
        mutable = {
            "product_id",
            "code",
            "price_type",
            "currency_definition_id",
            "meter_definition_id",
            "unit_amount",
            "interval_unit",
            "interval_count",
            "trial_period_days",
            "attributes",
        }
        if not mutable.intersection(self.model_fields_set):
            raise ValueError("At least one mutable field must be provided.")

        if "product_id" in self.model_fields_set and self.product_id is None:
            raise ValueError("ProductId must not be null.")
        if (
            "currency_definition_id" in self.model_fields_set
            and self.currency_definition_id is None
        ):
            raise ValueError("CurrencyDefinitionId must not be null.")
        if "code" in self.model_fields_set:
            self.code = self._required_text(self.code, "Code")
        if "price_type" in self.model_fields_set:
            self.price_type = self._required_text(self.price_type, "PriceType")
        if self.price_type is not None:
            self.price_type = self.price_type.lower()
        self.interval_unit = self._optional_text(
            self.interval_unit,
            "IntervalUnit",
        )
        if self.interval_unit is not None:
            self.interval_unit = self.interval_unit.lower()
        if "attributes" in self.model_fields_set:
            self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingMeterDefinitionCreateValidation(_GlobalCatalogValidation):
    """Validate global meter-definition creation."""

    code: str
    unit: str
    aggregation_mode: str = "sum"
    description: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingMeterDefinitionCreateValidation":
        self.code = self._required_text(self.code, "Code").casefold()
        self.unit = self._required_text(self.unit, "Unit").casefold()
        self.aggregation_mode = self._required_text(
            self.aggregation_mode,
            "AggregationMode",
        ).casefold()
        if self.unit not in {"minute", "unit", "task"}:
            raise ValueError("Unit must be minute, unit, or task.")
        if self.aggregation_mode not in {"sum", "max", "latest"}:
            raise ValueError("AggregationMode must be sum, max, or latest.")
        self.description = self._optional_text(self.description, "Description")
        self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingMeterDefinitionUpdateValidation(_GlobalCatalogValidation):
    """Validate global meter-definition updates."""

    code: str | None = None
    unit: str | None = None
    aggregation_mode: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingMeterDefinitionUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")
        if "code" in self.model_fields_set:
            self.code = self._required_text(self.code, "Code").casefold()
        if "unit" in self.model_fields_set:
            self.unit = self._required_text(self.unit, "Unit").casefold()
            if self.unit not in {"minute", "unit", "task"}:
                raise ValueError("Unit must be minute, unit, or task.")
        if "aggregation_mode" in self.model_fields_set:
            self.aggregation_mode = self._required_text(
                self.aggregation_mode,
                "AggregationMode",
            ).casefold()
            if self.aggregation_mode not in {"sum", "max", "latest"}:
                raise ValueError("AggregationMode must be sum, max, or latest.")
        if "description" in self.model_fields_set:
            self.description = self._optional_text(self.description, "Description")
        if "attributes" in self.model_fields_set:
            self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingPriceEntitlementCreateValidation(_GlobalCatalogValidation):
    """Validate global Price entitlement creation."""

    price_id: uuid.UUID
    meter_definition_id: uuid.UUID
    included_quantity: NonNegativeInt
    rollover_policy: str = "none"
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingPriceEntitlementCreateValidation":
        self.rollover_policy = self._required_text(
            self.rollover_policy,
            "RolloverPolicy",
        ).casefold()
        if self.rollover_policy != "none":
            raise ValueError("Only RolloverPolicy 'none' is currently supported.")
        self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingPriceEntitlementUpdateValidation(_GlobalCatalogValidation):
    """Validate global Price entitlement updates."""

    price_id: uuid.UUID | None = None
    meter_definition_id: uuid.UUID | None = None
    included_quantity: NonNegativeInt | None = None
    rollover_policy: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingPriceEntitlementUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")
        for field_name in ("price_id", "meter_definition_id", "included_quantity"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} must not be null.")
        if "rollover_policy" in self.model_fields_set:
            self.rollover_policy = self._required_text(
                self.rollover_policy,
                "RolloverPolicy",
            ).casefold()
            if self.rollover_policy != "none":
                raise ValueError("Only RolloverPolicy 'none' is currently supported.")
        if "attributes" in self.model_fields_set:
            self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingRunDefinitionCreateValidation(_NamedDefinitionValidation):
    """Validate global billing-run definition creation."""

    frequency: str
    interval_count: PositiveInt = 1
    timezone: str

    @model_validator(mode="after")
    def _normalize(self) -> "BillingRunDefinitionCreateValidation":
        self._normalize_definition()
        self.frequency = self._required_text(self.frequency, "Frequency").casefold()
        if self.frequency not in {"manual", "daily", "weekly", "monthly", "yearly"}:
            raise ValueError("Frequency is not supported.")
        self.timezone = self._required_text(self.timezone, "Timezone")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Timezone must be a valid IANA timezone.") from exc
        return self


class BillingRunDefinitionUpdateValidation(_NamedDefinitionUpdateValidation):
    """Validate global billing-run definition updates."""

    frequency: str | None = None
    interval_count: PositiveInt | None = None
    timezone: str | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingRunDefinitionUpdateValidation":
        self._normalize_definition_update({"frequency", "interval_count", "timezone"})
        if "frequency" in self.model_fields_set:
            self.frequency = self._required_text(
                self.frequency,
                "Frequency",
            ).casefold()
            if self.frequency not in {
                "manual",
                "daily",
                "weekly",
                "monthly",
                "yearly",
            }:
                raise ValueError("Frequency is not supported.")
        if "interval_count" in self.model_fields_set and self.interval_count is None:
            raise ValueError("IntervalCount must not be null.")
        if "timezone" in self.model_fields_set:
            self.timezone = self._required_text(self.timezone, "Timezone")
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Timezone must be a valid IANA timezone.") from exc
        return self


class BillingTaxCodeCreateValidation(_NamedDefinitionValidation):
    """Validate global tax-code creation."""

    @model_validator(mode="after")
    def _normalize(self) -> "BillingTaxCodeCreateValidation":
        self._normalize_definition()
        return self


class BillingTaxCodeUpdateValidation(_NamedDefinitionUpdateValidation):
    """Validate global tax-code updates."""

    @model_validator(mode="after")
    def _normalize(self) -> "BillingTaxCodeUpdateValidation":
        self._normalize_definition_update()
        return self


class BillingTaxRateCreateValidation(_GlobalCatalogValidation):
    """Validate effective-dated global tax-rate creation."""

    code: str
    tax_code_id: uuid.UUID
    jurisdiction_code: str
    rate_basis_points: NonNegativeInt
    effective_from: datetime
    effective_to: datetime | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingTaxRateCreateValidation":
        self.code = self._required_text(self.code, "Code").casefold()
        self.jurisdiction_code = self._required_text(
            self.jurisdiction_code,
            "JurisdictionCode",
        ).casefold()
        if self.rate_basis_points > 10000:
            raise ValueError("RateBasisPoints must not exceed 10000.")
        _require_aware_datetime(self.effective_from, "EffectiveFrom")
        _require_aware_datetime(self.effective_to, "EffectiveTo")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("EffectiveTo must be later than EffectiveFrom.")
        self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingTaxRateUpdateValidation(_GlobalCatalogValidation):
    """Validate effective-dated global tax-rate updates."""

    code: str | None = None
    tax_code_id: uuid.UUID | None = None
    jurisdiction_code: str | None = None
    rate_basis_points: NonNegativeInt | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingTaxRateUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")
        if "code" in self.model_fields_set:
            self.code = self._required_text(self.code, "Code").casefold()
        if "tax_code_id" in self.model_fields_set and self.tax_code_id is None:
            raise ValueError("TaxCodeId must not be null.")
        if "jurisdiction_code" in self.model_fields_set:
            self.jurisdiction_code = self._required_text(
                self.jurisdiction_code,
                "JurisdictionCode",
            ).casefold()
        if self.rate_basis_points is not None and self.rate_basis_points > 10000:
            raise ValueError("RateBasisPoints must not exceed 10000.")
        if "effective_from" in self.model_fields_set and self.effective_from is None:
            raise ValueError("EffectiveFrom must not be null.")
        if "effective_from" in self.model_fields_set:
            _require_aware_datetime(self.effective_from, "EffectiveFrom")
        if "effective_to" in self.model_fields_set:
            _require_aware_datetime(self.effective_to, "EffectiveTo")
        if "attributes" in self.model_fields_set:
            self.attributes = self._normalize_attributes(self.attributes)
        return self


class BillingPaymentTermCreateValidation(_NamedDefinitionValidation):
    """Validate global payment-term creation."""

    due_days: NonNegativeInt

    @model_validator(mode="after")
    def _normalize(self) -> "BillingPaymentTermCreateValidation":
        self._normalize_definition()
        return self


class BillingPaymentTermUpdateValidation(_NamedDefinitionUpdateValidation):
    """Validate global payment-term updates."""

    due_days: NonNegativeInt | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingPaymentTermUpdateValidation":
        self._normalize_definition_update({"due_days"})
        if "due_days" in self.model_fields_set and self.due_days is None:
            raise ValueError("DueDays must not be null.")
        return self


class BillingInvoiceTemplateCreateValidation(_NamedDefinitionValidation):
    """Validate global invoice-template creation."""

    locale: str
    template_format: str
    subject_template: str | None = None
    body_template: str

    @model_validator(mode="after")
    def _normalize(self) -> "BillingInvoiceTemplateCreateValidation":
        self._normalize_definition()
        self.locale = self._required_text(self.locale, "Locale")
        self.template_format = self._required_text(
            self.template_format,
            "TemplateFormat",
        ).casefold()
        if self.template_format not in {"html", "text"}:
            raise ValueError("TemplateFormat must be html or text.")
        self.subject_template = self._optional_text(
            self.subject_template,
            "SubjectTemplate",
        )
        self.body_template = self._required_text(self.body_template, "BodyTemplate")
        return self


class BillingInvoiceTemplateUpdateValidation(_NamedDefinitionUpdateValidation):
    """Validate global invoice-template updates."""

    locale: str | None = None
    template_format: str | None = None
    subject_template: str | None = None
    body_template: str | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingInvoiceTemplateUpdateValidation":
        self._normalize_definition_update(
            {"locale", "template_format", "subject_template", "body_template"}
        )
        if "locale" in self.model_fields_set:
            self.locale = self._required_text(self.locale, "Locale")
        if "template_format" in self.model_fields_set:
            self.template_format = self._required_text(
                self.template_format,
                "TemplateFormat",
            ).casefold()
            if self.template_format not in {"html", "text"}:
                raise ValueError("TemplateFormat must be html or text.")
        if "subject_template" in self.model_fields_set:
            self.subject_template = self._optional_text(
                self.subject_template,
                "SubjectTemplate",
            )
        if "body_template" in self.model_fields_set:
            self.body_template = self._required_text(
                self.body_template,
                "BodyTemplate",
            )
        return self


class BillingDiscountDefinitionCreateValidation(_NamedDefinitionValidation):
    """Validate global discount-definition creation."""

    kind: str
    percentage_basis_points: NonNegativeInt | None = None
    amount: NonNegativeInt | None = None
    currency_definition_id: uuid.UUID | None = None
    coupon_code: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingDiscountDefinitionCreateValidation":
        self._normalize_definition()
        self.kind = self._required_text(self.kind, "Kind").casefold()
        self.coupon_code = self._optional_text(self.coupon_code, "CouponCode")
        if self.coupon_code is not None:
            self.coupon_code = self.coupon_code.casefold()
        self._validate_benefit()
        return self

    def _validate_benefit(self) -> None:
        _require_aware_datetime(self.valid_from, "ValidFrom")
        _require_aware_datetime(self.valid_until, "ValidUntil")
        if self.kind == "percentage":
            if (
                self.percentage_basis_points is None
                or self.percentage_basis_points > 10000
            ):
                raise ValueError("Percentage discounts require 0..10000 basis points.")
            if self.amount is not None or self.currency_definition_id is not None:
                raise ValueError("Percentage discounts must omit amount and currency.")
        elif self.kind == "fixed_amount":
            if self.amount is None or self.currency_definition_id is None:
                raise ValueError("Fixed discounts require amount and currency.")
            if self.percentage_basis_points is not None:
                raise ValueError("Fixed discounts must omit percentage basis points.")
        else:
            raise ValueError("Kind must be percentage or fixed_amount.")
        if self.valid_until is not None and self.valid_from is not None:
            if self.valid_until <= self.valid_from:
                raise ValueError("ValidUntil must be later than ValidFrom.")


class BillingDiscountDefinitionUpdateValidation(_GlobalCatalogValidation):
    """Validate global discount-definition updates as a complete benefit."""

    display_name: str | None = None
    description: str | None = None
    coupon_code: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingDiscountDefinitionUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")
        if "display_name" in self.model_fields_set:
            self.display_name = self._required_text(self.display_name, "DisplayName")
        if "description" in self.model_fields_set:
            self.description = self._optional_text(self.description, "Description")
        if "coupon_code" in self.model_fields_set:
            self.coupon_code = self._optional_text(self.coupon_code, "CouponCode")
            if self.coupon_code is not None:
                self.coupon_code = self.coupon_code.casefold()
        if "attributes" in self.model_fields_set:
            self.attributes = self._normalize_attributes(self.attributes)
        if "valid_from" in self.model_fields_set:
            _require_aware_datetime(self.valid_from, "ValidFrom")
        if "valid_until" in self.model_fields_set:
            _require_aware_datetime(self.valid_until, "ValidUntil")
        if self.valid_until is not None and self.valid_from is not None:
            if self.valid_until <= self.valid_from:
                raise ValueError("ValidUntil must be later than ValidFrom.")
        return self


class BillingSubscriptionCreateValidation(IValidationBase):
    """Validate tenant Subscription creation and initial-period input."""

    tenant_id: uuid.UUID
    account_id: uuid.UUID
    price_id: uuid.UUID
    run_definition_id: uuid.UUID | None = None
    tax_code_id: uuid.UUID | None = None
    payment_term_id: uuid.UUID | None = None
    invoice_template_id: uuid.UUID | None = None
    discount_definition_id: uuid.UUID | None = None
    started_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_period(self) -> "BillingSubscriptionCreateValidation":
        _require_aware_datetime(self.started_at, "StartedAt")
        _require_aware_datetime(self.current_period_start, "CurrentPeriodStart")
        _require_aware_datetime(self.current_period_end, "CurrentPeriodEnd")
        if (self.current_period_start is None) != (self.current_period_end is None):
            raise ValueError(
                "CurrentPeriodStart and CurrentPeriodEnd must be provided together."
            )
        if self.current_period_start is not None:
            if self.current_period_end <= self.current_period_start:  # type: ignore
                raise ValueError(
                    "CurrentPeriodEnd must be later than CurrentPeriodStart."
                )
        if self.external_ref is not None:
            self.external_ref = self.external_ref.strip() or None
        return self


BillingSubscriptionUpdateValidation = build_update_validation(
    "BillingSubscriptionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingSubscription.",
    optional_uuid=(
        "run_definition_id",
        "tax_code_id",
        "payment_term_id",
        "invoice_template_id",
        "discount_definition_id",
    ),
    optional_text=("external_ref",),
    optional_datetime=("cancel_at",),
    optional_any=("attributes",),
)


class BillingSubscriptionPeriodValidation(IValidationBase):
    """Validate Subscription period advancement or reconciliation."""

    row_version: NonNegativeInt
    period_start: datetime | None = None
    period_end: datetime | None = None

    @model_validator(mode="after")
    def _validate_period(self) -> "BillingSubscriptionPeriodValidation":
        _require_aware_datetime(self.period_start, "PeriodStart")
        _require_aware_datetime(self.period_end, "PeriodEnd")
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("PeriodStart and PeriodEnd must be provided together.")
        if self.period_start is not None:
            assert self.period_end is not None
            if self.period_end <= self.period_start:
                raise ValueError("PeriodEnd must be later than PeriodStart.")
        return self


class BillingRunCreateValidation(IValidationBase):
    """Validate tenant Billing Run creation."""

    tenant_id: uuid.UUID
    definition_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    idempotency_key: str
    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "BillingRunCreateValidation":
        _require_aware_datetime(self.period_start, "PeriodStart")
        _require_aware_datetime(self.period_end, "PeriodEnd")
        if self.period_end <= self.period_start:
            raise ValueError("PeriodEnd must be later than PeriodStart.")
        self.idempotency_key = self.idempotency_key.strip()
        if not self.idempotency_key:
            raise ValueError("IdempotencyKey must be non-empty.")
        if self.subscription_id is not None and self.account_id is None:
            raise ValueError("Subscription-scoped runs require AccountId.")
        if self.external_ref is not None:
            self.external_ref = self.external_ref.strip() or None
        return self


BillingRunUpdateValidation = build_update_validation(
    "BillingRunUpdateValidation",
    module=__name__,
    doc="Validate mutable Billing Run metadata.",
    optional_text=("external_ref",),
    optional_any=("attributes",),
)


class BillingRunFailValidation(IValidationBase):
    """Validate a Billing Run failure transition."""

    row_version: NonNegativeInt
    failure_code: str
    failure_detail: str

    @model_validator(mode="after")
    def _normalize(self) -> "BillingRunFailValidation":
        self.failure_code = self.failure_code.strip().casefold()
        self.failure_detail = self.failure_detail.strip()
        if not self.failure_code or not self.failure_detail:
            raise ValueError("FailureCode and FailureDetail must be non-empty.")
        return self


class BillingRunRetryValidation(IValidationBase):
    """Validate a caller-controlled Billing Run retry."""

    row_version: NonNegativeInt
    idempotency_key: str

    @model_validator(mode="after")
    def _normalize(self) -> "BillingRunRetryValidation":
        self.idempotency_key = self.idempotency_key.strip()
        if not self.idempotency_key:
            raise ValueError("IdempotencyKey must be non-empty.")
        return self


class BillingEntitlementAdjustValidation(IValidationBase):
    """Validate a guarded entitlement adjustment."""

    row_version: NonNegativeInt
    quantity_delta: int
    reason: str
    idempotency_key: str

    @model_validator(mode="after")
    def _normalize(self) -> "BillingEntitlementAdjustValidation":
        if self.quantity_delta == 0:
            raise ValueError("QuantityDelta must be non-zero.")
        self.reason = self.reason.strip()
        self.idempotency_key = self.idempotency_key.strip()
        if not self.reason or not self.idempotency_key:
            raise ValueError("Reason and IdempotencyKey must be non-empty.")
        return self


BillingUsageEventCreateValidation = build_create_validation(
    "BillingUsageEventCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingUsageEvent.",
    required_uuid=("tenant_id", "account_id", "meter_definition_id"),
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
    optional_uuid=(
        "subscription_id",
        "billing_run_id",
        "currency_definition_id",
        "tax_code_id",
        "payment_term_id",
        "invoice_template_id",
        "discount_definition_id",
    ),
)

BillingInvoiceUpdateValidation = build_update_validation(
    "BillingInvoiceUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingInvoice.",
    optional_uuid=(
        "account_id",
        "subscription_id",
        "billing_run_id",
        "currency_definition_id",
        "tax_code_id",
        "payment_term_id",
        "invoice_template_id",
        "discount_definition_id",
    ),
    optional_text=("number",),
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
    required_uuid=("tenant_id", "account_id", "currency_definition_id"),
)

BillingCreditNoteUpdateValidation = build_update_validation(
    "BillingCreditNoteUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingCreditNote.",
    optional_uuid=("invoice_id", "currency_definition_id"),
    optional_text=("status", "number", "external_ref"),
    optional_datetime=("issued_at", "voided_at"),
    optional_any=("total_amount", "attributes"),
)

BillingAdjustmentCreateValidation = build_create_validation(
    "BillingAdjustmentCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingAdjustment.",
    required_uuid=("tenant_id", "account_id", "currency_definition_id"),
    required_text=("kind",),
    required_any=("amount",),
)

BillingAdjustmentUpdateValidation = build_update_validation(
    "BillingAdjustmentUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingAdjustment.",
    optional_uuid=("invoice_id", "credit_note_id", "currency_definition_id"),
    optional_text=("reason", "external_ref"),
    optional_datetime=("occurred_at",),
    optional_any=("attributes",),
)

BillingInvoiceLineCreateValidation = build_create_validation(
    "BillingInvoiceLineCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingInvoiceLine.",
    required_uuid=("tenant_id", "invoice_id"),
    optional_uuid=("price_id", "tax_code_id", "tax_rate_id"),
    required_any=("quantity", "amount"),
)

BillingInvoiceLineUpdateValidation = build_update_validation(
    "BillingInvoiceLineUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingInvoiceLine.",
    optional_uuid=("price_id", "tax_code_id", "tax_rate_id"),
    optional_text=("description",),
    optional_datetime=("period_start", "period_end"),
    optional_any=("quantity", "unit_amount", "amount", "attributes"),
)

BillingPaymentCreateValidation = build_create_validation(
    "BillingPaymentCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingPayment.",
    required_uuid=("tenant_id", "account_id", "currency_definition_id"),
    required_any=("amount",),
)

BillingPaymentUpdateValidation = build_update_validation(
    "BillingPaymentUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingPayment.",
    optional_uuid=("invoice_id", "currency_definition_id"),
    optional_text=("status", "provider", "external_ref"),
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
    required_uuid=("tenant_id", "account_id", "currency_definition_id"),
    required_text=("direction",),
    required_any=("amount",),
)
