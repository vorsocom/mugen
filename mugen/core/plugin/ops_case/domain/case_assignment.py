"""Provides a domain entity for the CaseAssignment DB model."""

from __future__ import annotations

__all__ = ["CaseAssignmentDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class CaseAssignmentDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_case CaseAssignment DB model."""

    case_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    queue_name: str | None = None

    assigned_by_user_id: uuid.UUID | None = None
    assigned_at: datetime | None = None
    unassigned_at: datetime | None = None
    is_active: bool | None = None

    reason: str | None = None
    attributes: dict[str, Any] | None = None

    case: "CaseDE" | None = None  # type: ignore

