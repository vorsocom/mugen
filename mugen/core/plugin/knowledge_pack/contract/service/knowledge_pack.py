"""Provides a service contract for KnowledgePackDE-related services."""

__all__ = ["IKnowledgePackService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.knowledge_pack.domain import KnowledgePackDE


class IKnowledgePackService(
    ICrudService[KnowledgePackDE],
    ABC,
):
    """A service contract for KnowledgePackDE-related services."""
