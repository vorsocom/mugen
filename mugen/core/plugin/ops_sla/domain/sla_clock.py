"""Provides a domain entity for the SlaClock DB model."""

__all__ = ["SlaClockDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class SlaClockDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaClock DB model."""

    policy_id: uuid.UUID | None = None
    calendar_id: uuid.UUID | None = None
    target_id: uuid.UUID | None = None
    clock_definition_id: uuid.UUID | None = None
    trace_id: str | None = None

    tracked_namespace: str | None = None
    tracked_id: uuid.UUID | None = None
    tracked_ref: str | None = None

    metric: str | None = None
    priority: str | None = None
    severity: str | None = None

    status: str | None = None

    started_at: datetime | None = None
    last_started_at: datetime | None = None
    paused_at: datetime | None = None
    stopped_at: datetime | None = None
    breached_at: datetime | None = None

    elapsed_seconds: int | None = None
    deadline_at: datetime | None = None

    is_breached: bool | None = None
    breach_count: int | None = None
    warned_offsets_json: list[int] | None = None

    last_actor_user_id: uuid.UUID | None = None

    attributes: dict[str, Any] | None = None
