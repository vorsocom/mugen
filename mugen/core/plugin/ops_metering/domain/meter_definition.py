"""Provides a domain entity for the MeterDefinition DB model."""

__all__ = ["MeterDefinitionDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class MeterDefinitionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_metering MeterDefinition DB model."""

    code: str | None = None
    unit: str | None = None
    aggregation_mode: str | None = None

    description: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
