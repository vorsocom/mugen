"""Provides a domain entity for the ConversationState DB model."""

__all__ = ["ConversationStateDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class ConversationStateDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration ConversationState model."""

    channel_profile_id: uuid.UUID | None = None
    policy_id: uuid.UUID | None = None

    sender_key: str | None = None
    external_conversation_ref: str | None = None

    status: str | None = None
    service_route_key: str | None = None
    route_key: str | None = None

    assigned_queue_name: str | None = None
    assigned_owner_user_id: uuid.UUID | None = None
    assigned_service_key: str | None = None

    last_intake_rule_id: uuid.UUID | None = None
    last_intake_result: str | None = None

    escalation_level: int | None = None
    is_escalated: bool | None = None

    is_throttled: bool | None = None
    throttled_until: datetime | None = None
    window_started_at: datetime | None = None
    window_message_count: int | None = None

    fallback_mode: str | None = None
    fallback_target: str | None = None
    fallback_reason: str | None = None
    is_fallback_active: bool | None = None

    last_activity_at: datetime | None = None

    attributes: dict[str, Any] | None = None
