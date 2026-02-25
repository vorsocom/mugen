"""Provides a domain entity for the SlaEscalationPolicy DB model."""

__all__ = ["SlaEscalationPolicyDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class SlaEscalationPolicyDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaEscalationPolicy DB model."""

    policy_key: str | None = None
    name: str | None = None
    description: str | None = None
    priority: int | None = None
    triggers_json: list[dict[str, Any]] | None = None
    actions_json: list[dict[str, Any]] | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
