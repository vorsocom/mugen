"""Provides a domain entity for the VendorVerificationCheck DB model."""

from __future__ import annotations

__all__ = ["VendorVerificationCheckDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class VendorVerificationCheckDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for criterion checks completed during a verification."""

    vendor_verification_id: uuid.UUID | None = None
    criterion_id: uuid.UUID | None = None
    criterion_code: str | None = None
    status: str | None = None
    is_required: bool | None = None
    checked_at: datetime | None = None
    due_at: datetime | None = None
    checked_by_user_id: uuid.UUID | None = None
    notes: str | None = None
    attributes: dict[str, Any] | None = None

    vendor_verification: "VendorVerificationDE" | None = None  # type: ignore
    criterion: "VerificationCriterionDE" | None = None  # type: ignore
    artifacts: Sequence["VendorVerificationArtifactDE"] | None = None  # type: ignore
