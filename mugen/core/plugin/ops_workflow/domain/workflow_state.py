"""Provides a domain entity for the WorkflowState DB model."""

from __future__ import annotations

__all__ = ["WorkflowStateDE"]

import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowStateDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_workflow WorkflowState DB model."""

    workflow_version_id: uuid.UUID | None = None

    key: str | None = None
    name: str | None = None

    is_initial: bool | None = None
    is_terminal: bool | None = None

    attributes: dict[str, Any] | None = None

    outgoing_transitions: Sequence["WorkflowTransitionDE"] | None = None  # type: ignore
    incoming_transitions: Sequence["WorkflowTransitionDE"] | None = None  # type: ignore
