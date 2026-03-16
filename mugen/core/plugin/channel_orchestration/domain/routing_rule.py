"""Provides a domain entity for the RoutingRule DB model."""

__all__ = ["RoutingRuleDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class RoutingRuleDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration RoutingRule model."""

    channel_profile_id: uuid.UUID | None = None

    route_key: str | None = None

    target_queue_name: str | None = None
    owner_user_id: uuid.UUID | None = None
    target_service_key: str | None = None
    target_namespace: str | None = None

    priority: int | None = None
    is_active: bool | None = None

    attributes: dict[str, Any] | None = None
