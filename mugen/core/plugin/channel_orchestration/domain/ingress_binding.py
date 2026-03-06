"""Provides a domain entity for the IngressBinding DB model."""

__all__ = ["IngressBindingDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class IngressBindingDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration IngressBinding model."""

    channel_profile_id: uuid.UUID | None = None
    channel_key: str | None = None
    identifier_type: str | None = None
    identifier_value: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
