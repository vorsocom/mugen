"""Provides a domain entity for the DataHandlingRecord DB model."""

__all__ = ["DataHandlingRecordDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class DataHandlingRecordDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for data handling request metadata."""

    retention_policy_id: uuid.UUID | None = None

    subject_namespace: str | None = None
    subject_id: uuid.UUID | None = None
    subject_ref: str | None = None

    request_type: str | None = None
    request_status: str | None = None

    requested_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None

    resolution_note: str | None = None
    handled_by_user_id: uuid.UUID | None = None
    evidence_ref: str | None = None

    meta: dict[str, Any] | None = None
