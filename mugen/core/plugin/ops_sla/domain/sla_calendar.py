"""Provides a domain entity for the SlaCalendar DB model."""

__all__ = ["SlaCalendarDE"]

from dataclasses import dataclass
from datetime import time
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class SlaCalendarDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaCalendar DB model."""

    code: str | None = None
    name: str | None = None
    timezone: str | None = None

    business_start_time: time | None = None
    business_end_time: time | None = None

    business_days: list[int] | None = None
    holiday_refs: list[str] | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
