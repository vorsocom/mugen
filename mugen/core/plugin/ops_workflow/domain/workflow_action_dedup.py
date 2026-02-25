"""Provides a domain entity for the WorkflowActionDedup DB model."""

from __future__ import annotations

__all__ = ["WorkflowActionDedupDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowActionDedupDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_workflow WorkflowActionDedup DB model."""

    workflow_instance_id: uuid.UUID | None = None
    action_name: str | None = None
    client_action_key: str | None = None
    request_hash: str | None = None
    response_code: int | None = None
    response_json: dict[str, Any] | None = None
    completed_at: datetime | None = None
    last_actor_user_id: uuid.UUID | None = None
