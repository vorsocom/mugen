"""Provides a domain entity for the AuditBizTraceEvent DB model."""

__all__ = ["AuditBizTraceEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class AuditBizTraceEventDE(BaseDE):
    """A domain entity for audit business trace timeline events."""

    tenant_id: uuid.UUID | None = None

    trace_id: str | None = None

    span_id: str | None = None

    parent_span_id: str | None = None

    correlation_id: str | None = None

    request_id: str | None = None

    source_plugin: str | None = None

    entity_set: str | None = None

    action_name: str | None = None

    stage: str | None = None

    status_code: int | None = None

    duration_ms: int | None = None

    details_json: dict[str, Any] | None = None

    occurred_at: datetime | None = None
