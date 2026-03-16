"""Provides a domain entity for the WorkflowTask DB model."""

from __future__ import annotations

__all__ = ["WorkflowTaskDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowTaskDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_workflow WorkflowTask DB model."""

    workflow_instance_id: uuid.UUID | None = None
    workflow_transition_id: uuid.UUID | None = None

    task_kind: str | None = None
    status: str | None = None

    title: str | None = None
    description: str | None = None

    assignee_user_id: uuid.UUID | None = None
    queue_name: str | None = None
    assigned_by_user_id: uuid.UUID | None = None
    assigned_at: datetime | None = None

    handoff_count: int | None = None

    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    completed_by_user_id: uuid.UUID | None = None
    outcome: str | None = None

    payload: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None

    events: Sequence["WorkflowEventDE"] | None = None  # type: ignore
