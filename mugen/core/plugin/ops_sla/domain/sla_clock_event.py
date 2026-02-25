"""Provides a domain entity for the SlaClockEvent DB model."""

__all__ = ["SlaClockEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class SlaClockEventDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaClockEvent DB model."""

    clock_id: uuid.UUID | None = None
    clock_definition_id: uuid.UUID | None = None
    event_type: str | None = None
    warned_offset_seconds: int | None = None
    trace_id: str | None = None
    occurred_at: datetime | None = None
    actor_user_id: uuid.UUID | None = None
    payload_json: dict[str, Any] | None = None
