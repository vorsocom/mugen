"""Provides a CRUD service for knowledge entries."""

__all__ = ["KnowledgeEntryService"]

from typing import Any, Mapping
import uuid

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.knowledge_pack.contract.service.knowledge_entry import (
    IKnowledgeEntryService,
)
from mugen.core.plugin.knowledge_pack.domain import KnowledgeEntryDE
from mugen.core.plugin.knowledge_pack.service.projection_guard import (
    KnowledgeProjectionMutationGuard,
)


class KnowledgeEntryService(
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
        self._projection_guard = KnowledgeProjectionMutationGuard(rsg)

    async def create(self, values: Mapping[str, Any]) -> KnowledgeEntryDE:
        """Create an entry only while its version is mutable."""
        await self._projection_guard.assert_mutable(
            tenant_id=uuid.UUID(str(values["tenant_id"])),
            knowledge_pack_version_id=uuid.UUID(
                str(values["knowledge_pack_version_id"])
            ),
        )
        return await super().create(values)

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> KnowledgeEntryDE | None:
        """Update an entry only while its version is mutable."""
        current = await self.get(where)
        if current is None:
            return None
        if current.tenant_id is None or current.knowledge_pack_version_id is None:
            return None
        await self._projection_guard.assert_mutable(
            tenant_id=current.tenant_id,
            knowledge_pack_version_id=current.knowledge_pack_version_id,
        )
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=changes,
        )
