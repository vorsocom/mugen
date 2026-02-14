"""Provides a domain entity for the EntitlementBucket DB model."""

__all__ = ["EntitlementBucketDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class EntitlementBucketDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing EntitlementBucket DB model."""

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None

    meter_code: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None

    included_quantity: int | None = None
    consumed_quantity: int | None = None
    rollover_quantity: int | None = None

    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    account: "AccountDE | None" = None  # type: ignore
    subscription: "SubscriptionDE | None" = None  # type: ignore
    price: "PriceDE | None" = None  # type: ignore
    usage_allocations: Sequence["UsageAllocationDE"] | None = None  # type: ignore
