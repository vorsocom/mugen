"""Provides a domain entity for the KnowledgeEntryRevision DB model."""

__all__ = ["KnowledgeEntryRevisionDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class KnowledgeEntryRevisionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the knowledge_pack KnowledgeEntryRevision DB model."""

    knowledge_entry_id: uuid.UUID | None = None
    knowledge_pack_version_id: uuid.UUID | None = None

    revision_number: int | None = None
    status: str | None = None

    body: str | None = None
    body_json: dict[str, Any] | None = None

    channel: str | None = None
    locale: str | None = None
    category: str | None = None

    published_at: datetime | None = None
    published_by_user_id: uuid.UUID | None = None

    archived_at: datetime | None = None
    archived_by_user_id: uuid.UUID | None = None

    attributes: dict[str, Any] | None = None

    scopes: Sequence["KnowledgeScopeDE"] | None = None  # type: ignore
