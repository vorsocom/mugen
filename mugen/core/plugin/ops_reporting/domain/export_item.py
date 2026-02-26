"""Provides a domain entity for the ExportItem DB model."""

__all__ = ["ExportItemDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ExportItemDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_reporting ExportItem DB model."""

    export_job_id: uuid.UUID | None = None

    item_index: int | None = None

    resource_type: str | None = None
    resource_id: uuid.UUID | None = None

    content_hash: str | None = None
    content_json: dict[str, Any] | None = None

    meta_json: dict[str, Any] | None = None
