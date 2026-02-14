"""Provides a domain entity for the RatedUsage DB model."""

__all__ = ["RatedUsageDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class RatedUsageDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_metering RatedUsage DB model."""

    usage_record_id: uuid.UUID | None = None

    meter_definition_id: uuid.UUID | None = None
    meter_policy_id: uuid.UUID | None = None

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None

    meter_code: str | None = None
    unit: str | None = None

    measured_quantity: int | None = None
    capped_quantity: int | None = None
    multiplier_bps: int | None = None
    billable_quantity: int | None = None

    occurred_at: datetime | None = None
    rated_at: datetime | None = None

    status: str | None = None
    voided_at: datetime | None = None
    void_reason: str | None = None

    billing_usage_event_id: uuid.UUID | None = None
    billing_external_ref: str | None = None

    attributes: dict[str, Any] | None = None
