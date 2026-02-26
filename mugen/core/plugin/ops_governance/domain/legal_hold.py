"""Provides a domain entity for LegalHold DB model."""

__all__ = ["LegalHoldDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class LegalHoldDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for legal holds across governed resources."""

    retention_class_id: uuid.UUID | None = None

    resource_type: str | None = None
    resource_id: uuid.UUID | None = None

    reason: str | None = None
    hold_until: datetime | None = None

    status: str | None = None
    placed_at: datetime | None = None
    placed_by_user_id: uuid.UUID | None = None

    released_at: datetime | None = None
    released_by_user_id: uuid.UUID | None = None
    release_reason: str | None = None

    attributes: dict[str, Any] | None = None
