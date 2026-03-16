"""Provides a domain entity for the AggregationJob DB model."""

__all__ = ["AggregationJobDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class AggregationJobDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_reporting AggregationJob DB model."""

    metric_definition_id: uuid.UUID | None = None

    window_start: datetime | None = None
    window_end: datetime | None = None

    bucket_minutes: int | None = None
    scope_key: str | None = None

    idempotency_key: str | None = None

    status: str | None = None

    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_run_at: datetime | None = None

    error_message: str | None = None

    created_by_user_id: uuid.UUID | None = None

    attributes: dict[str, Any] | None = None
