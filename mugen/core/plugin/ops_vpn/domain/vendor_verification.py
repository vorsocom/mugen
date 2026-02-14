"""Provides a domain entity for the VendorVerification DB model."""

from __future__ import annotations

__all__ = ["VendorVerificationDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class VendorVerificationDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn VendorVerification DB model."""

    vendor_id: uuid.UUID | None = None
    verification_type: str | None = None
    status: str | None = None
    checked_at: datetime | None = None
    due_at: datetime | None = None
    checked_by_user_id: uuid.UUID | None = None
    notes: str | None = None
    attributes: dict[str, Any] | None = None

    vendor: "VendorDE" | None = None  # type: ignore
    checks: Sequence["VendorVerificationCheckDE"] | None = None  # type: ignore
    artifacts: Sequence["VendorVerificationArtifactDE"] | None = None  # type: ignore
