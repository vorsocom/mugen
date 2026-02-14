"""Provides a domain entity for the UsageRecord DB model."""

__all__ = ["UsageRecordDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class UsageRecordDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_metering UsageRecord DB model."""

    meter_definition_id: uuid.UUID | None = None
    meter_policy_id: uuid.UUID | None = None

    usage_session_id: uuid.UUID | None = None
    rated_usage_id: uuid.UUID | None = None

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None

    occurred_at: datetime | None = None

    measured_minutes: int | None = None
    measured_units: int | None = None
    measured_tasks: int | None = None

    status: str | None = None
    rated_at: datetime | None = None

    voided_at: datetime | None = None
    void_reason: str | None = None

    idempotency_key: str | None = None
    external_ref: str | None = None

    attributes: dict[str, Any] | None = None
