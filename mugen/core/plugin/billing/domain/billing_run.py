"""Provides a domain entity for the BillingRun DB model."""

__all__ = ["BillingRunDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class BillingRunDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing BillingRun DB model."""

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None

    run_type: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    status: str | None = None  # pending / running / succeeded / failed / canceled
    idempotency_key: str | None = None

    started_at: datetime | None = None
    finished_at: datetime | None = None
    external_ref: str | None = None
    error_message: str | None = None
    attributes: dict[str, Any] | None = None

    account: "AccountDE | None" = None  # type: ignore
    subscription: "SubscriptionDE | None" = None  # type: ignore
