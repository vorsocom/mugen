"""Provides domain entities for global billing definitions."""

__all__ = [
    "CurrencyDefinitionDE",
    "DiscountDefinitionDE",
    "InvoiceTemplateDE",
    "MeterDefinitionDE",
    "PaymentTermDE",
    "PriceEntitlementDE",
    "RunDefinitionDE",
    "TaxCodeDE",
    "TaxRateDE",
]

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TYPE_CHECKING
import uuid

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin

if TYPE_CHECKING:
    from mugen.core.plugin.billing.domain.price import PriceDE


@dataclass
class MeterDefinitionDE(BaseDE):
    """A domain entity for a global billing meter definition."""

    code: str | None = None
    unit: str | None = None
    aggregation_mode: str | None = None
    description: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class PriceEntitlementDE(BaseDE, SoftDeleteDEMixin):
    """A domain entity for a global Price entitlement rule."""

    price_id: uuid.UUID | None = None
    meter_definition_id: uuid.UUID | None = None
    included_quantity: int | None = None
    rollover_policy: str | None = None
    attributes: dict[str, Any] | None = None

    price: "PriceDE | None" = None
    meter_definition: "MeterDefinitionDE | None" = None


@dataclass
class RunDefinitionDE(BaseDE):
    """A domain entity for a global billing-run definition."""

    code: str | None = None
    display_name: str | None = None
    description: str | None = None
    frequency: str | None = None
    interval_count: int | None = None
    timezone: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class CurrencyDefinitionDE(BaseDE):
    """A domain entity for a supported ISO 4217 currency."""

    code: str | None = None
    numeric_code: str | None = None
    display_name: str | None = None
    minor_unit: int | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class TaxCodeDE(BaseDE):
    """A domain entity for a global tax code."""

    code: str | None = None
    display_name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class TaxRateDE(BaseDE):
    """A domain entity for an effective-dated tax rate."""

    code: str | None = None
    tax_code_id: uuid.UUID | None = None
    jurisdiction_code: str | None = None
    rate_basis_points: int | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class PaymentTermDE(BaseDE):
    """A domain entity for a global payment term."""

    code: str | None = None
    display_name: str | None = None
    description: str | None = None
    due_days: int | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class InvoiceTemplateDE(BaseDE):
    """A domain entity for a global invoice template."""

    code: str | None = None
    display_name: str | None = None
    description: str | None = None
    locale: str | None = None
    template_format: str | None = None
    subject_template: str | None = None
    body_template: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class DiscountDefinitionDE(BaseDE):
    """A domain entity for a global discount definition."""

    code: str | None = None
    display_name: str | None = None
    description: str | None = None
    kind: str | None = None
    percentage_basis_points: int | None = None
    amount: int | None = None
    currency_definition_id: uuid.UUID | None = None
    coupon_code: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
