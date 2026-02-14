"""Provides a domain entity for the WorkflowDefinition DB model."""

from __future__ import annotations

__all__ = ["WorkflowDefinitionDE"]

from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkflowDefinitionDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the ops_workflow WorkflowDefinition DB model."""

    key: str | None = None
    name: str | None = None
    description: str | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    versions: Sequence["WorkflowVersionDE"] | None = None  # type: ignore
    instances: Sequence["WorkflowInstanceDE"] | None = None  # type: ignore
