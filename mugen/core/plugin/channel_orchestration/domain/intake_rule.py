"""Provides a domain entity for the IntakeRule DB model."""

__all__ = ["IntakeRuleDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class IntakeRuleDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration IntakeRule model."""

    channel_profile_id: uuid.UUID | None = None

    name: str | None = None
    match_kind: str | None = None
    match_value: str | None = None

    route_key: str | None = None

    priority: int | None = None
    is_active: bool | None = None

    attributes: dict[str, Any] | None = None
