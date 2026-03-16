"""Provides a domain entity for the WorkflowVersion DB model."""

from __future__ import annotations

__all__ = ["WorkflowVersionDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowVersionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_workflow WorkflowVersion DB model."""

    workflow_definition_id: uuid.UUID | None = None

    version_number: int | None = None
    status: str | None = None
    is_default: bool | None = None

    published_at: datetime | None = None
    published_by_user_id: uuid.UUID | None = None

    attributes: dict[str, Any] | None = None

    states: Sequence["WorkflowStateDE"] | None = None  # type: ignore
    transitions: Sequence["WorkflowTransitionDE"] | None = None  # type: ignore
