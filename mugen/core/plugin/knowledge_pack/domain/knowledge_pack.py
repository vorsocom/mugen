"""Provides a domain entity for the KnowledgePack DB model."""

__all__ = ["KnowledgePackDE"]

import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class KnowledgePackDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the knowledge_pack KnowledgePack DB model."""

    key: str | None = None
    name: str | None = None
    description: str | None = None

    is_active: bool | None = None

    current_version_id: uuid.UUID | None = None
    attributes: dict[str, Any] | None = None

    versions: Sequence["KnowledgePackVersionDE"] | None = None  # type: ignore
