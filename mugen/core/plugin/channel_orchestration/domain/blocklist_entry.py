"""Provides a domain entity for the BlocklistEntry DB model."""

__all__ = ["BlocklistEntryDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class BlocklistEntryDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration BlocklistEntry model."""

    channel_profile_id: uuid.UUID | None = None

    sender_key: str | None = None
    reason: str | None = None

    blocked_at: datetime | None = None
    blocked_by_user_id: uuid.UUID | None = None

    expires_at: datetime | None = None

    is_active: bool | None = None

    unblocked_at: datetime | None = None
    unblocked_by_user_id: uuid.UUID | None = None
    unblock_reason: str | None = None

    attributes: dict[str, Any] | None = None
