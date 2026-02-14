"""Provides a domain entity for the PolicyDecisionLog DB model."""

__all__ = ["PolicyDecisionLogDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class PolicyDecisionLogDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for append-only policy decision outcomes."""

    policy_definition_id: uuid.UUID | None = None

    subject_namespace: str | None = None
    subject_id: uuid.UUID | None = None
    subject_ref: str | None = None

    decision: str | None = None
    outcome: str | None = None
    reason: str | None = None

    evaluated_at: datetime | None = None
    evaluator_user_id: uuid.UUID | None = None

    request_context: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None

    retention_until: datetime | None = None
