"""Provides a service contract for KnowledgeEntryRevisionDE-related services."""

__all__ = ["IKnowledgeEntryRevisionService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.knowledge_pack.domain import KnowledgeEntryRevisionDE


class IKnowledgeEntryRevisionService(
    ICrudService[KnowledgeEntryRevisionDE],
    ABC,
):
    """A service contract for KnowledgeEntryRevisionDE-related services."""
