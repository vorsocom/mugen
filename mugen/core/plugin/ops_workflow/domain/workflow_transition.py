"""Provides a domain entity for the WorkflowTransition DB model."""

from __future__ import annotations

__all__ = ["WorkflowTransitionDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowTransitionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_workflow WorkflowTransition DB model."""

    workflow_version_id: uuid.UUID | None = None

    key: str | None = None

    from_state_id: uuid.UUID | None = None
    to_state_id: uuid.UUID | None = None

    requires_approval: bool | None = None
    auto_assign_user_id: uuid.UUID | None = None
    auto_assign_queue: str | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
