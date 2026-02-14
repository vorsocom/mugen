"""Provides a domain entity for the WorkflowInstance DB model."""

from __future__ import annotations

__all__ = ["WorkflowInstanceDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowInstanceDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_workflow WorkflowInstance DB model."""

    workflow_definition_id: uuid.UUID | None = None
    workflow_version_id: uuid.UUID | None = None

    current_state_id: uuid.UUID | None = None
    pending_transition_id: uuid.UUID | None = None
    pending_task_id: uuid.UUID | None = None

    title: str | None = None
    external_ref: str | None = None

    status: str | None = None

    subject_namespace: str | None = None
    subject_id: uuid.UUID | None = None
    subject_ref: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None

    last_actor_user_id: uuid.UUID | None = None
    cancel_reason: str | None = None

    attributes: dict[str, Any] | None = None

    tasks: Sequence["WorkflowTaskDE"] | None = None  # type: ignore
    events: Sequence["WorkflowEventDE"] | None = None  # type: ignore
