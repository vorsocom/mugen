"""Provides a domain entity for the MetricSeries DB model."""

__all__ = ["MetricSeriesDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class MetricSeriesDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_reporting MetricSeries DB model."""

    metric_definition_id: uuid.UUID | None = None

    bucket_start: datetime | None = None
    bucket_end: datetime | None = None

    scope_key: str | None = None

    value_numeric: int | None = None
    source_count: int | None = None

    computed_at: datetime | None = None

    aggregation_key: str | None = None

    attributes: dict[str, Any] | None = None
