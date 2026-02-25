"""Provides a domain entity for the AuditCorrelationLink DB model."""

__all__ = ["AuditCorrelationLinkDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class AuditCorrelationLinkDE(BaseDE):
    """A domain entity for audit correlation graph links."""

    tenant_id: uuid.UUID | None = None

    trace_id: str | None = None

    correlation_id: str | None = None

    request_id: str | None = None

    source_plugin: str | None = None

    entity_set: str | None = None

    entity_id: uuid.UUID | None = None

    operation: str | None = None

    action_name: str | None = None

    parent_entity_set: str | None = None

    parent_entity_id: uuid.UUID | None = None

    occurred_at: datetime | None = None

    attributes: dict[str, Any] | None = None
