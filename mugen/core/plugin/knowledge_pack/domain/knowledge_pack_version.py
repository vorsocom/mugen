"""Provides a domain entity for the KnowledgePackVersion DB model."""

__all__ = ["KnowledgePackVersionDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class KnowledgePackVersionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the knowledge_pack KnowledgePackVersion DB model."""

    knowledge_pack_id: uuid.UUID | None = None

    version_number: int | None = None
    status: str | None = None

    submitted_at: datetime | None = None
    submitted_by_user_id: uuid.UUID | None = None

    approved_at: datetime | None = None
    approved_by_user_id: uuid.UUID | None = None

    published_at: datetime | None = None
    published_by_user_id: uuid.UUID | None = None

    archived_at: datetime | None = None
    archived_by_user_id: uuid.UUID | None = None

    rollback_of_version_id: uuid.UUID | None = None

    note: str | None = None
    attributes: dict[str, Any] | None = None

    entries: Sequence["KnowledgeEntryDE"] | None = None  # type: ignore
