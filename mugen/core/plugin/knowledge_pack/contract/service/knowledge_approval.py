"""Provides a service contract for KnowledgeApprovalDE-related services."""

__all__ = ["IKnowledgeApprovalService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.knowledge_pack.domain import KnowledgeApprovalDE


class IKnowledgeApprovalService(
    ICrudService[KnowledgeApprovalDE],
    ABC,
):
    """A service contract for KnowledgeApprovalDE-related services."""
