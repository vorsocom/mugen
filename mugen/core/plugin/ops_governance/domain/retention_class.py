"""Provides a domain entity for RetentionClass DB model."""

__all__ = ["RetentionClassDE"]

from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class RetentionClassDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for lifecycle retention classes."""

    code: str | None = None
    name: str | None = None
    resource_type: str | None = None

    retention_days: int | None = None
    redaction_after_days: int | None = None
    purge_grace_days: int | None = None

    legal_hold_allowed: bool | None = None
    is_active: bool | None = None

    description: str | None = None
    attributes: dict[str, Any] | None = None
