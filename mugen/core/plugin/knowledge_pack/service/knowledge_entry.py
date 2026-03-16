"""Provides a CRUD service for knowledge entries."""

__all__ = ["KnowledgeEntryService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.knowledge_pack.contract.service.knowledge_entry import (
    IKnowledgeEntryService,
)
from mugen.core.plugin.knowledge_pack.domain import KnowledgeEntryDE


class KnowledgeEntryService(  # pylint: disable=too-few-public-methods
    IRelationalService[KnowledgeEntryDE],
    IKnowledgeEntryService,
):
    """A CRUD service for knowledge entries."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=KnowledgeEntryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
