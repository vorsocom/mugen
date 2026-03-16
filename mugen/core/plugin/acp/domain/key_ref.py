"""Provides a domain entity for the KeyRef DB model."""

__all__ = ["KeyRefDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class KeyRefDE(BaseDE):
    """A domain entity for managed key references."""

    tenant_id: uuid.UUID | None = None

    purpose: str | None = None
    key_id: str | None = None
    provider: str | None = None
    status: str | None = None

    activated_at: datetime | None = None
    retired_at: datetime | None = None
    retired_by_user_id: uuid.UUID | None = None
    retired_reason: str | None = None

    destroyed_at: datetime | None = None
    destroyed_by_user_id: uuid.UUID | None = None
    destroy_reason: str | None = None

    encrypted_secret: str | None = None
    has_material: bool | None = None
    material_last_set_at: datetime | None = None
    material_last_set_by_user_id: uuid.UUID | None = None

    attributes: dict[str, Any] | None = None
