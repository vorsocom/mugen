"""Guards governed content from mutation during active projection attempts."""

from __future__ import annotations

__all__ = ["KnowledgeProjectionMutationGuard"]

import uuid

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    ScalarFilter,
    ScalarFilterOp,
)


class KnowledgeProjectionMutationGuard:  # pylint: disable=too-few-public-methods
    """Reject writes while a version checksum is frozen for indexing."""

    _PROJECTION_TABLE = "knowledge_pack_knowledge_index_projection"

    def __init__(self, rsg: IRelationalStorageGateway) -> None:
        self._guard_rsg = rsg

    async def assert_mutable(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_version_id: uuid.UUID,
    ) -> None:
        """Reject content/scope mutation while a projection lease is active."""
        try:
            rows = await self._guard_rsg.find_many(
                self._PROJECTION_TABLE,
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "knowledge_pack_version_id": knowledge_pack_version_id,
                        },
                        scalar_filters=[
                            ScalarFilter(
                                field="status",
                                op=ScalarFilterOp.IN,
                                value=["queued", "processing"],
                            )
                        ],
                    )
                ],
                limit=1,
            )
        except SQLAlchemyError:
            abort(500)
        if rows:
            abort(
                409,
                (
                    "Knowledge content is immutable while projection is queued "
                    "or processing."
                ),
            )
