"""Provides a domain entity for LifecycleActionLog DB model."""

__all__ = ["LifecycleActionLogDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class LifecycleActionLogDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for append-only lifecycle logs."""

    resource_type: str | None = None
    resource_id: uuid.UUID | None = None

    action_type: str | None = None
    outcome: str | None = None
    dry_run: bool | None = None

    actor_user_id: uuid.UUID | None = None
    correlation_id: str | None = None

    details: dict[str, Any] | None = None
