"""Provides a domain entity for the KpiThreshold DB model."""

__all__ = ["KpiThresholdDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class KpiThresholdDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_reporting KpiThreshold DB model."""

    metric_definition_id: uuid.UUID | None = None

    scope_key: str | None = None

    target_value: int | None = None

    warn_low: int | None = None
    warn_high: int | None = None

    critical_low: int | None = None
    critical_high: int | None = None

    description: str | None = None
    is_active: bool | None = None

    attributes: dict[str, Any] | None = None
