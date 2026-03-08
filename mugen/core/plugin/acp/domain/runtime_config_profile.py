"""Provides a domain entity for the RuntimeConfigProfile DB model."""

__all__ = ["RuntimeConfigProfileDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class RuntimeConfigProfileDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for ACP-owned runtime config overlays."""

    category: str | None = None
    profile_key: str | None = None
    display_name: str | None = None
    is_active: bool | None = None
    settings_json: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
