"""Provides a domain entity for the KnowledgeScope DB model."""

__all__ = ["KnowledgeScopeDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class KnowledgeScopeDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the knowledge_pack KnowledgeScope DB model."""

    knowledge_pack_version_id: uuid.UUID | None = None
    knowledge_entry_revision_id: uuid.UUID | None = None

    channel: str | None = None
    locale: str | None = None
    category: str | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
