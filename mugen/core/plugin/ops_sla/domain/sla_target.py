"""Provides a domain entity for the SlaTarget DB model."""

__all__ = ["SlaTargetDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class SlaTargetDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaTarget DB model."""

    policy_id: uuid.UUID | None = None

    metric: str | None = None
    priority: str | None = None
    severity: str | None = None

    target_minutes: int | None = None
    warn_before_minutes: int | None = None

    auto_breach: bool | None = None
    attributes: dict[str, Any] | None = None
