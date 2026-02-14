"""Provides a domain entity for the WorkflowEvent DB model."""

from __future__ import annotations

__all__ = ["WorkflowEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowEventDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_workflow WorkflowEvent DB model."""

    workflow_instance_id: uuid.UUID | None = None
    workflow_task_id: uuid.UUID | None = None

    event_type: str | None = None

    from_state_id: uuid.UUID | None = None
    to_state_id: uuid.UUID | None = None

    actor_user_id: uuid.UUID | None = None
    occurred_at: datetime | None = None

    note: str | None = None
    payload: dict[str, Any] | None = None
