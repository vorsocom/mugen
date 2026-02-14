"""Provides a domain entity for the VendorPerformanceEvent DB model."""

from __future__ import annotations

__all__ = ["VendorPerformanceEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class VendorPerformanceEventDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn VendorPerformanceEvent DB model."""

    vendor_id: uuid.UUID | None = None
    metric_type: str | None = None
    observed_at: datetime | None = None

    metric_value: int | None = None
    metric_numerator: int | None = None
    metric_denominator: int | None = None
    normalized_score: int | None = None
    sample_size: int | None = None

    unit: str | None = None
    attributes: dict[str, Any] | None = None

    vendor: "VendorDE" | None = None  # type: ignore
