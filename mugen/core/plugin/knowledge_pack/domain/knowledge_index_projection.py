"""Provides the domain entity for Knowledge Index Projections."""

__all__ = ["KnowledgeIndexProjectionDE"]

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import uuid

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class KnowledgeIndexProjectionDE(BaseDE, TenantScopedDEMixin):
    """A tenant-scoped durable search projection attempt."""

    knowledge_pack_id: uuid.UUID | None = None
    knowledge_pack_version_id: uuid.UUID | None = None

    provider: str | None = None
    target_fingerprint: str | None = None
    content_checksum: str | None = None
    projection_schema_version: int | None = None

    operation: str | None = None
    status: str | None = None

    document_count: int | None = None
    attempt_count: int | None = None
    max_attempts: int | None = None

    lease_owner: str | None = None
    lease_expires_at: datetime | None = None

    requested_by_user_id: uuid.UUID | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None

    failure_code: str | None = None
    failure_detail: str | None = None
    is_current_ready: bool | None = None
    request_payload: dict[str, Any] | None = None
