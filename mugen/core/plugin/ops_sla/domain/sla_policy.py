"""Provides a domain entity for the SlaPolicy DB model."""

__all__ = ["SlaPolicyDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class SlaPolicyDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaPolicy DB model."""

    code: str | None = None
    name: str | None = None
    description: str | None = None

    calendar_id: uuid.UUID | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
