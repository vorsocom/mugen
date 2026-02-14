"""Provides a domain entity for the VendorCapability DB model."""

from __future__ import annotations

__all__ = ["VendorCapabilityDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class VendorCapabilityDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn VendorCapability DB model."""

    vendor_id: uuid.UUID | None = None
    capability_code: str | None = None
    service_region: str | None = None
    attributes: dict[str, Any] | None = None

    vendor: "VendorDE" | None = None  # type: ignore
