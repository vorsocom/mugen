"""Provides a domain entity for the DelegationGrant DB model."""

__all__ = ["DelegationGrantDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class DelegationGrantDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for delegation grant/revocation records."""

    principal_user_id: uuid.UUID | None = None
    delegate_user_id: uuid.UUID | None = None

    scope: str | None = None
    purpose: str | None = None

    status: str | None = None
    effective_from: datetime | None = None
    expires_at: datetime | None = None

    source_grant_id: uuid.UUID | None = None
    revoked_at: datetime | None = None
    revoked_by_user_id: uuid.UUID | None = None
    revocation_reason: str | None = None

    attributes: dict[str, Any] | None = None
