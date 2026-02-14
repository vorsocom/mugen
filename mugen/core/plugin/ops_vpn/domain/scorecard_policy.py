"""Provides a domain entity for the ScorecardPolicy DB model."""

from __future__ import annotations

__all__ = ["ScorecardPolicyDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ScorecardPolicyDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn ScorecardPolicy DB model."""

    code: str | None = None
    display_name: str | None = None

    time_to_quote_weight: int | None = None
    completion_rate_weight: int | None = None
    complaint_rate_weight: int | None = None
    response_sla_weight: int | None = None

    min_sample_size: int | None = None
    minimum_overall_score: int | None = None
    require_all_metrics: bool | None = None

    attributes: dict[str, Any] | None = None
