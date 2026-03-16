"""Provides scope-bounded retrieval helpers for published revisions."""

__all__ = ["KnowledgeScopeService"]

import uuid
from typing import Sequence

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import (
    IRelationalStorageGateway,
)
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.knowledge_pack.contract.service.knowledge_scope import (
    IKnowledgeScopeService,
)
from mugen.core.plugin.knowledge_pack.domain import (
    KnowledgeEntryRevisionDE,
    KnowledgeScopeDE,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_entry_revision import (
    KnowledgeEntryRevisionService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_pack_version import (
    KnowledgePackVersionService,
)


class KnowledgeScopeService(
    IRelationalService[KnowledgeScopeDE],
    IKnowledgeScopeService,
):
    """A CRUD service for retrieval scope rows and scope-filtered published lookup."""

    _VERSION_TABLE = "knowledge_pack_knowledge_pack_version"
    _REVISION_TABLE = "knowledge_pack_knowledge_entry_revision"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=KnowledgeScopeDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._version_service = KnowledgePackVersionService(
            table=self._VERSION_TABLE,
            rsg=rsg,
        )
        self._revision_service = KnowledgeEntryRevisionService(
            table=self._REVISION_TABLE,
            rsg=rsg,
        )

    async def list_published_revisions(
        self,
        *,
        tenant_id: uuid.UUID,
        channel: str | None = None,
        locale: str | None = None,
        category: str | None = None,
    ) -> Sequence[KnowledgeEntryRevisionDE]:
        """Retrieve published revisions constrained by scope dimensions."""
        where: dict[str, object] = {
            "tenant_id": tenant_id,
            "is_active": True,
        }
        if channel is not None:
            where["channel"] = channel
        if locale is not None:
            where["locale"] = locale
        if category is not None:
            where["category"] = category

        try:
            scopes = await self.list(
                filter_groups=[
                    FilterGroup(
                        where=where,
                    )
                ],
                limit=2_000,
            )
        except SQLAlchemyError:
            abort(500)

        if not scopes:
            return []

        revision_ids: set[uuid.UUID] = set()
        for scope in scopes:
            if scope.knowledge_entry_revision_id is None:
                continue
            if scope.knowledge_pack_version_id is None:
                continue

            try:
                version = await self._version_service.get(
                    {
                        "tenant_id": tenant_id,
                        "id": scope.knowledge_pack_version_id,
                    }
                )
                revision = await self._revision_service.get(
                    {
                        "tenant_id": tenant_id,
                        "id": scope.knowledge_entry_revision_id,
                    }
                )
            except SQLAlchemyError:
                abort(500)

            if version is None or revision is None:
                continue

            if version.status != "published":
                continue
            if revision.status != "published":
                continue

            revision_ids.add(scope.knowledge_entry_revision_id)

        if not revision_ids:
            return []

        try:
            revisions = await self._revision_service.list(
                filter_groups=[
                    FilterGroup(
                        where={"tenant_id": tenant_id},
                        scalar_filters=[
                            ScalarFilter(
                                field="id",
                                op=ScalarFilterOp.IN,
                                value=list(revision_ids),
                            )
                        ],
                    )
                ],
                limit=len(revision_ids),
            )
        except SQLAlchemyError:
            abort(500)

        return [
            revision
            for revision in revisions
            if revision.status == "published"
        ]
