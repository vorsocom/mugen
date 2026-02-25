"""Provides a domain entity for the WorkflowDecisionRequest DB model."""

from __future__ import annotations

__all__ = ["WorkflowDecisionRequestDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowDecisionRequestDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for workflow decision requests."""

    trace_id: str | None = None
    template_key: str | None = None
    status: str | None = None

    requester_actor_json: dict[str, Any] | None = None
    assigned_to_json: dict[str, Any] | None = None
    options_json: dict[str, Any] | None = None
    context_json: dict[str, Any] | None = None

    workflow_instance_id: uuid.UUID | None = None
    workflow_task_id: uuid.UUID | None = None

    due_at: datetime | None = None
    resolved_at: datetime | None = None

    attributes: dict[str, Any] | None = None
