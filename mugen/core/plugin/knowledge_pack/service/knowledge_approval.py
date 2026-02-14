"""Provides a CRUD service for knowledge governance approvals."""

__all__ = ["KnowledgeApprovalService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.knowledge_pack.contract.service.knowledge_approval import (
    IKnowledgeApprovalService,
)
from mugen.core.plugin.knowledge_pack.domain import KnowledgeApprovalDE


class KnowledgeApprovalService(  # pylint: disable=too-few-public-methods
    IRelationalService[KnowledgeApprovalDE],
    IKnowledgeApprovalService,
):
    """A CRUD service for knowledge governance approvals."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=KnowledgeApprovalDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
