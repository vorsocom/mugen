"""Provides a domain entity for the ReportDefinition DB model."""

__all__ = ["ReportDefinitionDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ReportDefinitionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_reporting ReportDefinition DB model."""

    code: str | None = None
    name: str | None = None

    description: str | None = None

    metric_codes: list[str] | None = None

    filters_json: dict[str, Any] | None = None
    group_by_json: list[str] | None = None

    is_active: bool | None = None

    attributes: dict[str, Any] | None = None
