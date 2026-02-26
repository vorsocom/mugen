"""Provides a domain entity for the ReportSnapshot DB model."""

__all__ = ["ReportSnapshotDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class ReportSnapshotDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_reporting ReportSnapshot DB model."""

    report_definition_id: uuid.UUID | None = None
    metric_codes: list[str] | None = None

    status: str | None = None

    window_start: datetime | None = None
    window_end: datetime | None = None

    scope_key: str | None = None

    summary_json: dict[str, Any] | None = None

    trace_id: str | None = None
    provenance_json: dict[str, Any] | None = None
    manifest_hash: str | None = None
    signature_json: dict[str, Any] | None = None

    generated_at: datetime | None = None
    published_at: datetime | None = None
    archived_at: datetime | None = None

    generated_by_user_id: uuid.UUID | None = None
    published_by_user_id: uuid.UUID | None = None
    archived_by_user_id: uuid.UUID | None = None

    note: str | None = None

    attributes: dict[str, Any] | None = None
