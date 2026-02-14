"""Provides a domain entity for the UsageSession DB model."""

__all__ = ["UsageSessionDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class UsageSessionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_metering UsageSession DB model."""

    meter_definition_id: uuid.UUID | None = None
    meter_policy_id: uuid.UUID | None = None

    usage_record_id: uuid.UUID | None = None

    tracked_namespace: str | None = None
    tracked_id: uuid.UUID | None = None
    tracked_ref: str | None = None

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None

    status: str | None = None

    started_at: datetime | None = None
    last_started_at: datetime | None = None
    paused_at: datetime | None = None
    stopped_at: datetime | None = None

    elapsed_seconds: int | None = None

    idempotency_key: str | None = None
    last_actor_user_id: uuid.UUID | None = None

    attributes: dict[str, Any] | None = None
