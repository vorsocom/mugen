"""Provides a domain entity for the ChannelProfile DB model."""

__all__ = ["ChannelProfileDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ChannelProfileDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration ChannelProfile model."""

    channel_key: str | None = None
    profile_key: str | None = None
    display_name: str | None = None

    route_default_key: str | None = None
    policy_id: uuid.UUID | None = None

    is_active: bool | None = None

    attributes: dict[str, Any] | None = None
