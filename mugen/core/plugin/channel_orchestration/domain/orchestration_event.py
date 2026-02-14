"""Provides a domain entity for the OrchestrationEvent DB model."""

__all__ = ["OrchestrationEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class OrchestrationEventDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration OrchestrationEvent model."""

    conversation_state_id: uuid.UUID | None = None
    channel_profile_id: uuid.UUID | None = None

    sender_key: str | None = None

    event_type: str | None = None
    decision: str | None = None
    reason: str | None = None

    payload: dict[str, Any] | None = None

    actor_user_id: uuid.UUID | None = None

    occurred_at: datetime | None = None

    source: str | None = None
