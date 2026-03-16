"""Provides a domain entity for the ConnectorCallLog DB model."""

__all__ = ["ConnectorCallLogDE"]

from datetime import datetime
import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ConnectorCallLogDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_connector ConnectorCallLog DB model."""

    trace_id: str | None = None
    connector_instance_id: uuid.UUID | None = None
    capability_name: str | None = None
    client_action_key: str | None = None

    request_json: Any = None
    request_hash: str | None = None

    response_json: Any = None
    response_hash: str | None = None

    status: str | None = None
    http_status_code: int | None = None
    attempt_count: int | None = None
    duration_ms: int | None = None

    error_json: Any = None
    escalation_json: Any = None

    invoked_by_user_id: uuid.UUID | None = None
    invoked_at: datetime | None = None
    attributes: dict[str, Any] | None = None
