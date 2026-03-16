"""Provides a domain entity for the WorkflowDecisionOutcome DB model."""

from __future__ import annotations

__all__ = ["WorkflowDecisionOutcomeDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowDecisionOutcomeDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for workflow decision outcomes."""

    decision_request_id: uuid.UUID | None = None
    resolver_actor_json: dict[str, Any] | None = None
    outcome_json: dict[str, Any] | None = None
    signature_json: dict[str, Any] | None = None
