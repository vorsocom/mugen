"""Provides a domain entity for the MetricDefinition DB model."""

__all__ = ["MetricDefinitionDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class MetricDefinitionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_reporting MetricDefinition DB model."""

    code: str | None = None
    name: str | None = None

    formula_type: str | None = None

    source_table: str | None = None
    source_time_column: str | None = None
    source_value_column: str | None = None
    scope_column: str | None = None

    source_filter: dict[str, Any] | None = None

    description: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
