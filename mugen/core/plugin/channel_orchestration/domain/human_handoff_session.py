"""Provides a domain entity for HumanHandoffSession rows."""

__all__ = ["HumanHandoffSessionDE"]

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import uuid

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class HumanHandoffSessionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for durable human handoff state."""

    scope_key: str | None = None
    platform: str | None = None
    channel_id: str | None = None
    room_id: str | None = None
    sender_id: str | None = None
    conversation_id: str | None = None
    client_profile_id: uuid.UUID | None = None
    service_route_key: str | None = None

    status: str | None = None
    owner_user_id: uuid.UUID | None = None
    reason: str | None = None
    activated_at: datetime | None = None
    deactivated_at: datetime | None = None
    deactivated_by_user_id: uuid.UUID | None = None
    deactivation_reason: str | None = None

    last_human_reply_at: datetime | None = None
    last_user_message_at: datetime | None = None
    last_transcript_sequence_no: int | None = None
    last_delivery_status: str | None = None
    last_delivery_error: str | None = None
    attributes: dict[str, Any] | None = None
