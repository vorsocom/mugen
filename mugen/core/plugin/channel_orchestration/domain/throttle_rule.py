"""Provides a domain entity for the ThrottleRule DB model."""

__all__ = ["ThrottleRuleDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ThrottleRuleDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration ThrottleRule model."""

    channel_profile_id: uuid.UUID | None = None

    code: str | None = None
    sender_scope: str | None = None

    window_seconds: int | None = None
    max_messages: int | None = None

    block_on_violation: bool | None = None
    block_duration_seconds: int | None = None

    priority: int | None = None
    is_active: bool | None = None

    attributes: dict[str, Any] | None = None
