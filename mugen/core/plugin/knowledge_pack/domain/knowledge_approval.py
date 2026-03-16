"""Provides a domain entity for the KnowledgeApproval DB model."""

__all__ = ["KnowledgeApprovalDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class KnowledgeApprovalDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the knowledge_pack KnowledgeApproval DB model."""

    knowledge_pack_version_id: uuid.UUID | None = None
    knowledge_entry_revision_id: uuid.UUID | None = None

    action: str | None = None

    actor_user_id: uuid.UUID | None = None
    occurred_at: datetime | None = None

    note: str | None = None
    payload: dict[str, Any] | None = None
