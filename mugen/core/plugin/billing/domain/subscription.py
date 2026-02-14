"""Provides a domain entity for the Subscription DB model."""

__all__ = ["SubscriptionDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class SubscriptionDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the billing Subscription DB model."""

    account_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None

    status: str | None = None  # active / trialing / paused / canceled / ended

    started_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None

    cancel_at: datetime | None = None
    canceled_at: datetime | None = None
    ended_at: datetime | None = None

    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    account: "AccountDE | None" = None  # type: ignore
    price: "PriceDE | None" = None  # type: ignore
    invoices: Sequence["InvoiceDE"] | None = None  # type: ignore
    usage_events: Sequence["UsageEventDE"] | None = None  # type: ignore
    billing_runs: Sequence["BillingRunDE"] | None = None  # type: ignore
    entitlement_buckets: Sequence["EntitlementBucketDE"] | None = None  # type: ignore
