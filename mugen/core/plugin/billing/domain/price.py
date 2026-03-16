"""Provides a domain entity for the Price DB model."""

__all__ = ["PriceDE"]

import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class PriceDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the billing Price DB model."""

    product_id: uuid.UUID | None = None

    code: str | None = None
    price_type: str | None = None  # one_time / recurring / metered

    currency: str | None = None
    unit_amount: int | None = None  # minor units

    interval_unit: str | None = None  # day / week / month / year
    interval_count: int | None = None
    trial_period_days: int | None = None

    usage_unit: str | None = None  # e.g., "api_call", "gb"
    meter_code: str | None = None
    attributes: dict[str, Any] | None = None

    product: "ProductDE | None" = None  # type: ignore
    subscriptions: Sequence["SubscriptionDE"] | None = None  # type: ignore
    entitlement_buckets: Sequence["EntitlementBucketDE"] | None = None  # type: ignore
