"""Provides a domain entity for the SlaEscalationRun DB model."""

__all__ = ["SlaEscalationRunDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class SlaEscalationRunDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaEscalationRun DB model."""

    escalation_policy_id: uuid.UUID | None = None
    clock_id: uuid.UUID | None = None
    clock_event_id: uuid.UUID | None = None
    status: str | None = None
    trigger_event_json: dict[str, Any] | None = None
    results_json: list[dict[str, Any]] | dict[str, Any] | None = None
    trace_id: str | None = None
    executed_at: datetime | None = None
    executed_by_user_id: uuid.UUID | None = None
