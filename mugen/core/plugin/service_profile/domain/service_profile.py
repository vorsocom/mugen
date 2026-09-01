"""Provides a domain entity for the Service Profile model."""

from __future__ import annotations

__all__ = ["ServiceProfileDE"]

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ServiceProfileDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for a tenant-scoped Service Profile."""

    key: str | None = None
    display_name: str | None = None
    status: str | None = None
    activated_at: datetime | None = None
    disabled_at: datetime | None = None
    attributes: dict[str, Any] | None = None
