"""Domain entities for the agent_runtime plugin."""

from __future__ import annotations

__all__ = [
    "AgentPlanRunDE",
    "AgentPlanStepDE",
]

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class AgentPlanRunDE(BaseDE, TenantScopedDEMixin):
    """Durable plan-run state row."""

    scope_key: str | None = None
    mode: str | None = None
    status: str | None = None
    service_route_key: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    agent_key: str | None = None
    spawned_by_step_no: int | None = None
    request_json: dict[str, Any] | None = None
    policy_json: dict[str, Any] | None = None
    run_state_json: dict[str, Any] | None = None
    join_state_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None
    current_sequence_no: int | None = None
    next_wakeup_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    final_outcome_json: dict[str, Any] | None = None
    last_error: str | None = None


@dataclass
class AgentPlanStepDE(BaseDE, TenantScopedDEMixin):
    """Append-only plan-run step row."""

    run_id: str | None = None
    sequence_no: int | None = None
    step_kind: str | None = None
    payload_json: dict[str, Any] | None = None
    occurred_at: datetime | None = None
