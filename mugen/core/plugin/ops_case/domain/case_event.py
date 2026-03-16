"""Provides a domain entity for the CaseEvent DB model."""

from __future__ import annotations

__all__ = ["CaseEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class CaseEventDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_case CaseEvent DB model."""

    case_id: uuid.UUID | None = None
    event_type: str | None = None
    status_from: str | None = None
    status_to: str | None = None

    note: str | None = None
    payload: dict[str, Any] | None = None

    actor_user_id: uuid.UUID | None = None
    occurred_at: datetime | None = None

    case: "CaseDE" | None = None  # type: ignore

