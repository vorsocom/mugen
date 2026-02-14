"""Provides a domain entity for the RetentionPolicy DB model."""

__all__ = ["RetentionPolicyDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class RetentionPolicyDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for retention/redaction policy metadata."""

    code: str | None = None
    name: str | None = None

    target_namespace: str | None = None
    target_entity: str | None = None

    description: str | None = None

    retention_days: int | None = None
    redaction_after_days: int | None = None

    legal_hold_allowed: bool | None = None
    action_mode: str | None = None
    downstream_job_ref: str | None = None

    is_active: bool | None = None

    last_action_applied_at: datetime | None = None
    last_action_type: str | None = None
    last_action_status: str | None = None
    last_action_note: str | None = None
    last_action_by_user_id: uuid.UUID | None = None

    attributes: dict[str, Any] | None = None
