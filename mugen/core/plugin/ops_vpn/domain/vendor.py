"""Provides a domain entity for the Vendor DB model."""

from __future__ import annotations

__all__ = ["VendorDE"]

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class VendorDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the ops_vpn Vendor DB model."""

    code: str | None = None
    display_name: str | None = None
    status: str | None = None

    onboarding_completed_at: datetime | None = None

    reverification_cadence_days: int | None = None
    last_reverified_at: datetime | None = None
    next_reverification_due_at: datetime | None = None

    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    categories: Sequence["VendorCategoryDE"] | None = None  # type: ignore
    capabilities: Sequence["VendorCapabilityDE"] | None = None  # type: ignore
    verifications: Sequence["VendorVerificationDE"] | None = None  # type: ignore
    performance_events: Sequence["VendorPerformanceEventDE"] | None = None
    scorecards: Sequence["VendorScorecardDE"] | None = None  # type: ignore
