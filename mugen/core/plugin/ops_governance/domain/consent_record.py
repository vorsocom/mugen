"""Provides a domain entity for the ConsentRecord DB model."""

__all__ = ["ConsentRecordDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ConsentRecordDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for consent grant/withdrawal records."""

    subject_user_id: uuid.UUID | None = None

    controller_namespace: str | None = None
    purpose: str | None = None
    scope: str | None = None
    legal_basis: str | None = None

    status: str | None = None
    effective_at: datetime | None = None
    expires_at: datetime | None = None

    source_consent_id: uuid.UUID | None = None
    withdrawn_at: datetime | None = None
    withdrawn_by_user_id: uuid.UUID | None = None
    withdrawal_reason: str | None = None

    attributes: dict[str, Any] | None = None
