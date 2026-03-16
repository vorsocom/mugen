"""Provides a domain entity for the PolicyDefinition DB model."""

__all__ = ["PolicyDefinitionDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class PolicyDefinitionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for governance policy definitions."""

    code: str | None = None
    name: str | None = None

    description: str | None = None
    policy_type: str | None = None
    rule_ref: str | None = None

    evaluation_mode: str | None = None
    engine: str | None = None
    version: int | None = None
    is_active: bool | None = None

    last_evaluated_at: datetime | None = None
    last_evaluated_by_user_id: uuid.UUID | None = None
    last_decision_log_id: uuid.UUID | None = None

    document_json: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
