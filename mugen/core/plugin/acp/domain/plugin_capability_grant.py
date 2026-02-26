"""Provides a domain entity for PluginCapabilityGrant DB records."""

__all__ = ["PluginCapabilityGrantDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class PluginCapabilityGrantDE(BaseDE):
    """A domain entity for plugin capability grants."""

    tenant_id: uuid.UUID | None = None

    plugin_key: str | None = None
    capabilities: list[str] | None = None

    granted_at: datetime | None = None
    granted_by_user_id: uuid.UUID | None = None
    expires_at: datetime | None = None

    revoked_at: datetime | None = None
    revoked_by_user_id: uuid.UUID | None = None
    revoke_reason: str | None = None

    attributes: dict[str, Any] | None = None
