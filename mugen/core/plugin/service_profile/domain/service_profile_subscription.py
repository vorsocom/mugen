"""Provides a domain entity for Service Profile Subscription assignments."""

from __future__ import annotations

__all__ = ["ServiceProfileSubscriptionDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ServiceProfileSubscriptionDE(
    BaseDE,
    TenantScopedDEMixin,
    SoftDeleteDEMixin,
):
    """A domain entity for a profile's exact Subscription allocation."""

    service_profile_id: uuid.UUID | None = None
    billing_subscription_id: uuid.UUID | None = None
    product_code: str | None = None
    status: str | None = None
    activated_at: datetime | None = None
    disabled_at: datetime | None = None
    attributes: dict[str, Any] | None = None
