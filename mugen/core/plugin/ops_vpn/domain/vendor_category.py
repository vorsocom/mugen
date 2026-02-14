"""Provides a domain entity for the VendorCategory DB model."""

from __future__ import annotations

__all__ = ["VendorCategoryDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class VendorCategoryDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn VendorCategory DB model."""

    vendor_id: uuid.UUID | None = None
    category_code: str | None = None
    display_name: str | None = None
    attributes: dict[str, Any] | None = None

    vendor: "VendorDE" | None = None  # type: ignore
