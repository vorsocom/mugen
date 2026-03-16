"""Provides a domain entity for the VendorScorecard DB model."""

from __future__ import annotations

__all__ = ["VendorScorecardDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class VendorScorecardDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn VendorScorecard DB model."""

    vendor_id: uuid.UUID | None = None

    period_start: datetime | None = None
    period_end: datetime | None = None

    time_to_quote_score: int | None = None
    completion_rate_score: int | None = None
    complaint_rate_score: int | None = None
    response_sla_score: int | None = None
    overall_score: int | None = None

    event_count: int | None = None
    is_routable: bool | None = None
    status_flags: dict[str, Any] | None = None
    computed_at: datetime | None = None
    attributes: dict[str, Any] | None = None

    vendor: "VendorDE" | None = None  # type: ignore
