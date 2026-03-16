"""Provides a service contract for KnowledgeScopeDE-related services."""

__all__ = ["IKnowledgeScopeService"]

import uuid
from abc import ABC, abstractmethod
from typing import Sequence

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.knowledge_pack.domain import (
    KnowledgeEntryRevisionDE,
    KnowledgeScopeDE,
)


class IKnowledgeScopeService(
    ICrudService[KnowledgeScopeDE],
    ABC,
):
    """A service contract for KnowledgeScopeDE-related services."""

    @abstractmethod
    async def list_published_revisions(
        self,
        *,
        tenant_id: uuid.UUID,
        channel: str | None = None,
        locale: str | None = None,
        category: str | None = None,
    ) -> Sequence[KnowledgeEntryRevisionDE]:
        """List published knowledge entry revisions filtered by scope."""
