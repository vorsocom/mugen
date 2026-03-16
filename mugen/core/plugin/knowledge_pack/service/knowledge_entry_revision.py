"""Provides a CRUD service for knowledge entry revisions."""

__all__ = ["KnowledgeEntryRevisionService"]

from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.knowledge_pack.contract.service.knowledge_entry_revision import (
    IKnowledgeEntryRevisionService,
)
from mugen.core.plugin.knowledge_pack.domain import KnowledgeEntryRevisionDE


class KnowledgeEntryRevisionService(
    IRelationalService[KnowledgeEntryRevisionDE],
    IKnowledgeEntryRevisionService,
):
    """A CRUD service for knowledge entry revisions with publish immutability."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=KnowledgeEntryRevisionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> KnowledgeEntryRevisionDE | None:
        """Reject mutable updates once a revision has been published."""
        try:
            current = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if current is None:
            return None

        if current.status == "published":
            abort(
                409,
                "Published revisions are immutable. Create a new revision instead.",
            )

        try:
            return await super().update_with_row_version(
                where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)
