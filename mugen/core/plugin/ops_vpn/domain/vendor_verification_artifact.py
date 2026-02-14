"""Provides a domain entity for the VendorVerificationArtifact DB model."""

from __future__ import annotations

__all__ = ["VendorVerificationArtifactDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class VendorVerificationArtifactDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for evidence artifacts attached to verifications/checks."""

    vendor_verification_id: uuid.UUID | None = None
    verification_check_id: uuid.UUID | None = None
    artifact_type: str | None = None
    uri: str | None = None
    content_hash: str | None = None
    uploaded_by_user_id: uuid.UUID | None = None
    uploaded_at: datetime | None = None
    notes: str | None = None
    attributes: dict[str, Any] | None = None

    vendor_verification: "VendorVerificationDE" | None = None  # type: ignore
    verification_check: "VendorVerificationCheckDE" | None = None  # type: ignore
