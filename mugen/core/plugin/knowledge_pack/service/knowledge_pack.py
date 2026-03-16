"""Provides a CRUD service for knowledge packs."""

__all__ = ["KnowledgePackService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.knowledge_pack.contract.service.knowledge_pack import (
    IKnowledgePackService,
)
from mugen.core.plugin.knowledge_pack.domain import KnowledgePackDE


class KnowledgePackService(  # pylint: disable=too-few-public-methods
    IRelationalService[KnowledgePackDE],
    IKnowledgePackService,
):
    """A CRUD service for knowledge packs."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=KnowledgePackDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
