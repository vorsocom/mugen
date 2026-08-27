"""Provides the deprecated tenant meter compatibility domain entity."""

__all__ = ["MeterDefinitionDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class MeterDefinitionDE(BaseDE, TenantScopedDEMixin):
    """A read-only tenant projection of a canonical billing meter."""

    code: str | None = None
    unit: str | None = None
    aggregation_mode: str | None = None
    description: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
    is_deprecated: bool | None = None
    successor_entity_set: str | None = None
