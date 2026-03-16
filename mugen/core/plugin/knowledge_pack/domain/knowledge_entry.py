"""Provides a domain entity for the KnowledgeEntry DB model."""

__all__ = ["KnowledgeEntryDE"]

import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class KnowledgeEntryDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the knowledge_pack KnowledgeEntry DB model."""

    knowledge_pack_id: uuid.UUID | None = None
    knowledge_pack_version_id: uuid.UUID | None = None

    entry_key: str | None = None
    title: str | None = None
    summary: str | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    revisions: Sequence["KnowledgeEntryRevisionDE"] | None = None  # type: ignore
