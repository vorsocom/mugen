"""Provides a domain entity for entitlement adjustments."""

__all__ = ["EntitlementAdjustmentDE"]

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import uuid

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class EntitlementAdjustmentDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for an append-only entitlement adjustment."""

    bucket_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    quantity_delta: int | None = None
    adjustment_before: int | None = None
    adjustment_after: int | None = None
    capacity_after: int | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    actor_user_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    attributes: dict[str, Any] | None = None
