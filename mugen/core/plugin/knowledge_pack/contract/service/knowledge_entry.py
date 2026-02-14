"""Provides a service contract for KnowledgeEntryDE-related services."""

__all__ = ["IKnowledgeEntryService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.knowledge_pack.domain import KnowledgeEntryDE


class IKnowledgeEntryService(
    ICrudService[KnowledgeEntryDE],
    ABC,
):
    """A service contract for KnowledgeEntryDE-related services."""
