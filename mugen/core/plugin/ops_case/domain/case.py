"""Provides a domain entity for the Case DB model."""

from __future__ import annotations

__all__ = ["CaseDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class CaseDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the ops_case Case DB model."""

    case_number: str | None = None
    title: str | None = None
    description: str | None = None

    status: str | None = None
    priority: str | None = None
    severity: str | None = None

    due_at: datetime | None = None
    sla_target_at: datetime | None = None
    triaged_at: datetime | None = None
    escalated_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    cancelled_at: datetime | None = None

    owner_user_id: uuid.UUID | None = None
    queue_name: str | None = None

    escalation_level: int | None = None
    is_escalated: bool | None = None
    escalated_by_user_id: uuid.UUID | None = None

    created_by_user_id: uuid.UUID | None = None
    last_actor_user_id: uuid.UUID | None = None

    resolution_summary: str | None = None
    cancellation_reason: str | None = None
    attributes: dict[str, Any] | None = None

    events: Sequence["CaseEventDE"] | None = None  # type: ignore
    assignments: Sequence["CaseAssignmentDE"] | None = None  # type: ignore
    links: Sequence["CaseLinkDE"] | None = None  # type: ignore

