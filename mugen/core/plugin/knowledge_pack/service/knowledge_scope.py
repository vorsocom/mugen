"""Provides scope-bounded retrieval helpers for published revisions."""

__all__ = ["KnowledgeScopeService"]

import uuid
from typing import Any, Mapping, Sequence

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
from mugen.core.plugin.knowledge_pack.service.projection_guard import (
    KnowledgeProjectionMutationGuard,
)


class KnowledgeScopeService(
    IRelationalService[KnowledgeScopeDE],
    IKnowledgeScopeService,
):
    """A CRUD service for retrieval scope rows and scope-filtered published lookup."""

    _VERSION_TABLE = "knowledge_pack_knowledge_pack_version"
    _REVISION_TABLE = "knowledge_pack_knowledge_entry_revision"
    _SERVICE_PROFILE_TABLE = "service_profile_service_profile"

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
        self._projection_guard = KnowledgeProjectionMutationGuard(rsg)

    async def create(self, values: Mapping[str, Any]) -> KnowledgeScopeDE:
        """Create a scope only while its version is mutable."""
        await self._assert_service_profile_available(
            tenant_id=uuid.UUID(str(values["tenant_id"])),
            service_profile_id=(
                None
                if values.get("service_profile_id") is None
                else uuid.UUID(str(values["service_profile_id"]))
            ),
        )
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
    ) -> KnowledgeScopeDE | None:
        """Update a scope only while its version is mutable."""
        current = await self.get(where)
        if current is None:
            return None
        if current.tenant_id is None or current.knowledge_pack_version_id is None:
            return None
        await self._projection_guard.assert_mutable(
            tenant_id=current.tenant_id,
            knowledge_pack_version_id=current.knowledge_pack_version_id,
        )
        requested_profile_id = changes.get(
            "service_profile_id",
            current.service_profile_id,
        )
        await self._assert_service_profile_available(
            tenant_id=current.tenant_id,
            service_profile_id=(
                None
                if requested_profile_id is None
                else uuid.UUID(str(requested_profile_id))
            ),
        )
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=changes,
        )

    async def list_published_revisions(
        self,
        *,
        tenant_id: uuid.UUID,
        channel: str | None = None,
        locale: str | None = None,
        category: str | None = None,
        service_route_key: str | None = None,
        client_profile_key: str | None = None,
        service_profile_id: uuid.UUID | None = None,
    ) -> Sequence[KnowledgeEntryRevisionDE]:
        """Retrieve published revisions constrained by scope dimensions."""
        if service_profile_id is not None:
            profile = await self._rsg.get_one(
                self._SERVICE_PROFILE_TABLE,
                {
                    "tenant_id": tenant_id,
                    "id": service_profile_id,
                    "status": "active",
                    "deleted_at": None,
                },
            )
            if profile is None:
                return []
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

        service_route_options = self._scope_options(service_route_key)
        client_profile_options = self._scope_options(client_profile_key)
        service_profile_options = self._scope_options(service_profile_id)
        filter_groups = [
            FilterGroup(
                where={
                    **where,
                    "service_route_key": route_option,
                    "client_profile_key": profile_option,
                    "service_profile_id": service_profile_option,
                },
            )
            for route_option in service_route_options
            for profile_option in client_profile_options
            for service_profile_option in service_profile_options
        ]

        try:
            scopes = await self.list(
                filter_groups=filter_groups,
                limit=2_000,
            )
        except SQLAlchemyError:
            abort(500)

        if not scopes:
            return []

        revision_scores: dict[uuid.UUID, int] = {}
        revision_order: dict[uuid.UUID, int] = {}
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

            revision_id = scope.knowledge_entry_revision_id
            revision_scores[revision_id] = max(
                revision_scores.get(revision_id, -1),
                self._scope_specificity(
                    scope,
                    service_route_key=service_route_key,
                    client_profile_key=client_profile_key,
                    service_profile_id=service_profile_id,
                ),
            )
            revision_order.setdefault(revision_id, len(revision_order))

        if not revision_scores:
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
                                value=list(revision_scores),
                            )
                        ],
                    )
                ],
                limit=len(revision_scores),
            )
        except SQLAlchemyError:
            abort(500)

        published_revisions = [
            revision for revision in revisions if revision.status == "published"
        ]
        return sorted(
            published_revisions,
            key=lambda revision: (
                -revision_scores.get(revision.id, 0),
                revision_order.get(revision.id, len(revision_order)),
            ),
        )

    @staticmethod
    def _scope_options(value: Any | None) -> tuple[Any | None, ...]:
        return (None,) if value is None else (None, value)

    async def _assert_service_profile_available(
        self,
        *,
        tenant_id: uuid.UUID,
        service_profile_id: uuid.UUID | None,
    ) -> None:
        if service_profile_id is None:
            return
        try:
            profile = await self._rsg.get_one(
                self._SERVICE_PROFILE_TABLE,
                {
                    "tenant_id": tenant_id,
                    "id": service_profile_id,
                    "deleted_at": None,
                },
            )
        except SQLAlchemyError:
            abort(500)
        if profile is None:
            abort(
                400,
                "ServiceProfileId must reference an available route-tenant profile.",
            )

    @staticmethod
    def _scope_specificity(
        scope: KnowledgeScopeDE,
        *,
        service_route_key: str | None,
        client_profile_key: str | None,
        service_profile_id: uuid.UUID | None,
    ) -> int:
        specificity = 0
        if (
            service_route_key is not None
            and scope.service_route_key == service_route_key
        ):
            specificity += 1
        if (
            client_profile_key is not None
            and scope.client_profile_key == client_profile_key
        ):
            specificity += 1
        if (
            service_profile_id is not None
            and scope.service_profile_id == service_profile_id
        ):
            specificity += 1
        return specificity
