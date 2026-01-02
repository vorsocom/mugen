"""Provides a domain entity for the TenantInvitation DB model."""

__all__ = ["TenantInvitationDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class TenantInvitationDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the TenantDomain DB model."""

    email: str | None = None

    invited_by_user_id: uuid.UUID | None = None

    token_hash: str | None = None

    expires_at: datetime | None = None

    accepted_at: datetime | None = None

    accepted_by_user_id: uuid.UUID | None = None

    revoked_at: datetime | None = None

    revoked_by_user_id: uuid.UUID | None = None

    status: str | None = None
