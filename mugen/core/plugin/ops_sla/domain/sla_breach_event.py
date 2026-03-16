"""Provides a domain entity for the SlaBreachEvent DB model."""

__all__ = ["SlaBreachEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class SlaBreachEventDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_sla SlaBreachEvent DB model."""

    clock_id: uuid.UUID | None = None

    event_type: str | None = None
    occurred_at: datetime | None = None

    actor_user_id: uuid.UUID | None = None

    escalation_level: int | None = None
    reason: str | None = None
    note: str | None = None
    payload: dict[str, Any] | None = None
