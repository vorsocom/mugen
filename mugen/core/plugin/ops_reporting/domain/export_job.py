"""Provides a domain entity for the ExportJob DB model."""

__all__ = ["ExportJobDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class ExportJobDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_reporting ExportJob DB model."""

    trace_id: str | None = None

    export_type: str | None = None
    spec_json: dict[str, Any] | None = None

    status: str | None = None

    manifest_json: dict[str, Any] | None = None
    manifest_hash: str | None = None
    signature_json: dict[str, Any] | None = None

    export_ref: str | None = None
    policy_decision_json: dict[str, Any] | None = None

    error_message: str | None = None

    created_by_user_id: uuid.UUID | None = None
    completed_at: datetime | None = None

    attributes: dict[str, Any] | None = None
