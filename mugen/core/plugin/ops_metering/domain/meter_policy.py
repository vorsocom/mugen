"""Provides a domain entity for the MeterPolicy DB model."""

__all__ = ["MeterPolicyDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class MeterPolicyDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_metering MeterPolicy DB model."""

    meter_definition_id: uuid.UUID | None = None

    code: str | None = None
    name: str | None = None
    description: str | None = None

    cap_minutes: int | None = None
    cap_units: int | None = None
    cap_tasks: int | None = None

    multiplier_bps: int | None = None
    rounding_mode: str | None = None
    rounding_step: int | None = None

    billable_window_minutes: int | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
