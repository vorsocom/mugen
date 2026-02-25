"""Provides a domain entity for the SlaClockDefinition DB model."""

__all__ = ["SlaClockDefinitionDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class SlaClockDefinitionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaClockDefinition DB model."""

    code: str | None = None
    name: str | None = None
    description: str | None = None
    metric: str | None = None
    target_minutes: int | None = None
    warn_offsets_json: list[int] | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
