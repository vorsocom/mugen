"""Provides a domain entity for the RefreshToken DB model."""

__all__ = ["RefreshTokenDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.user_scoped import UserScopedDEMixin


@dataclass
class RefreshTokenDE(BaseDE, UserScopedDEMixin):
    """A domain entity for the RefreshToken DB model."""

    token_hash: str | None = None

    token_jti: uuid.UUID | None = None

    expires_at: datetime | None = None
