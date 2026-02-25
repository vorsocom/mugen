"""Provides a domain entity for the WorkItem DB model."""

__all__ = ["WorkItemDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class WorkItemDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the channel_orchestration WorkItem DB model."""

    trace_id: str | None = None
    source: str | None = None

    participants: dict[str, Any] | list[Any] | None = None
    content: dict[str, Any] | list[Any] | None = None
    attachments: dict[str, Any] | list[Any] | None = None
    signals: dict[str, Any] | list[Any] | None = None
    extractions: dict[str, Any] | list[Any] | None = None

    linked_case_id: uuid.UUID | None = None
    linked_workflow_instance_id: uuid.UUID | None = None

    replay_count: int | None = None
    last_replayed_at: datetime | None = None

    last_actor_user_id: uuid.UUID | None = None
    attributes: dict[str, Any] | None = None
