"""Provides a domain entity for the UsageEvent DB model."""

__all__ = ["UsageEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class UsageEventDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing UsageEvent DB model."""

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None
    meter_code: str | None = None

    occurred_at: datetime | None = None
    quantity: int | None = None

    status: str | None = None  # recorded / void
    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    usage_allocations: Sequence["UsageAllocationDE"] | None = None  # type: ignore
