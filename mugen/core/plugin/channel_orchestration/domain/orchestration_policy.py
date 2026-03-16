"""Provides a domain entity for the OrchestrationPolicy DB model."""

__all__ = ["OrchestrationPolicyDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class OrchestrationPolicyDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration OrchestrationPolicy model."""

    code: str | None = None
    name: str | None = None

    hours_mode: str | None = None
    escalation_mode: str | None = None

    fallback_policy: str | None = None
    fallback_target: str | None = None

    escalation_target: str | None = None
    escalation_after_seconds: int | None = None

    is_active: bool | None = None

    attributes: dict[str, Any] | None = None
