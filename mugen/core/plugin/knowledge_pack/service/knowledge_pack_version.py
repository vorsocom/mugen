"""Provides a CRUD service for knowledge pack version workflow actions."""

__all__ = ["KnowledgePackVersionService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping, Sequence

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.knowledge_pack.api.validation import (
    KnowledgePackApproveValidation,
    KnowledgePackArchiveValidation,
    KnowledgePackPublishValidation,
    KnowledgePackRejectValidation,
    KnowledgePackRollbackVersionValidation,
    KnowledgePackSubmitForReviewValidation,
)
from mugen.core.plugin.knowledge_pack.contract.service.knowledge_pack_version import (
    IKnowledgePackVersionService,
)
from mugen.core.plugin.knowledge_pack.domain import KnowledgePackVersionDE
from mugen.core.plugin.knowledge_pack.service.knowledge_approval import (
    KnowledgeApprovalService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_entry_revision import (
    KnowledgeEntryRevisionService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_pack import KnowledgePackService


class KnowledgePackVersionService(
    IRelationalService[KnowledgePackVersionDE],
    IKnowledgePackVersionService,
):
    """A CRUD service for knowledge pack version publish workflow."""

    _PACK_TABLE = "knowledge_pack_knowledge_pack"
    _REVISION_TABLE = "knowledge_pack_knowledge_entry_revision"
    _APPROVAL_TABLE = "knowledge_pack_knowledge_approval"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=KnowledgePackVersionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._pack_service = KnowledgePackService(table=self._PACK_TABLE, rsg=rsg)
        self._revision_service = KnowledgeEntryRevisionService(
            table=self._REVISION_TABLE,
            rsg=rsg,
        )
        self._approval_service = KnowledgeApprovalService(
            table=self._APPROVAL_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> KnowledgePackVersionDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Knowledge pack version not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_version_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> KnowledgePackVersionDE:
        svc: ICrudServiceWithRowVersion[KnowledgePackVersionDE] = self

        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return updated

    async def _record_approval(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_version_id: uuid.UUID,
        action: str,
        actor_user_id: uuid.UUID,
        note: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            await self._approval_service.create(
                {
                    "tenant_id": tenant_id,
                    "knowledge_pack_version_id": knowledge_pack_version_id,
                    "action": action,
                    "actor_user_id": actor_user_id,
                    "occurred_at": self._now_utc(),
                    "note": self._normalize_optional_text(note),
                    "payload": dict(payload) if payload is not None else None,
                }
            )
        except SQLAlchemyError:
            abort(500)

    async def _list_pack_versions_by_status(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_id: uuid.UUID,
        statuses: Sequence[str],
    ) -> Sequence[KnowledgePackVersionDE]:
        if not statuses:
            return []

        try:
            return await self.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "knowledge_pack_id": knowledge_pack_id,
                        },
                        scalar_filters=[
                            ScalarFilter(
                                field="status",
                                op=ScalarFilterOp.IN,
                                value=list(statuses),
                            )
                        ],
                    )
                ],
                limit=500,
            )
        except SQLAlchemyError:
            abort(500)

    async def _set_pack_current_version(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_id: uuid.UUID,
        current_version_id: uuid.UUID | None,
    ) -> None:
        try:
            await self._pack_service.update(
                where={
                    "tenant_id": tenant_id,
                    "id": knowledge_pack_id,
                },
                changes={"current_version_id": current_version_id},
            )
        except SQLAlchemyError:
            abort(500)

    async def _transition_revisions(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_version_id: uuid.UUID,
        from_statuses: set[str],
        to_status: str,
        actor_user_id: uuid.UUID,
    ) -> None:
        now = self._now_utc()

        try:
            revisions = await self._revision_service.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "knowledge_pack_version_id": knowledge_pack_version_id,
                        },
                    )
                ],
                limit=5_000,
            )
        except SQLAlchemyError:
            abort(500)

        for revision in revisions:
            if revision.id is None:
                continue
            if revision.status not in from_statuses:
                continue

            changes: dict[str, Any] = {"status": to_status}
            if to_status == "published":
                changes["published_at"] = now
                changes["published_by_user_id"] = actor_user_id
                changes["archived_at"] = None
                changes["archived_by_user_id"] = None
            if to_status == "archived":
                changes["archived_at"] = now
                changes["archived_by_user_id"] = actor_user_id

            try:
                await self._revision_service.update(
                    where={
                        "tenant_id": tenant_id,
                        "id": revision.id,
                    },
                    changes=changes,
                )
            except SQLAlchemyError:
                abort(500)

    async def _validate_no_unreviewed_revisions(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_version_id: uuid.UUID,
    ) -> None:
        try:
            revisions = await self._revision_service.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "knowledge_pack_version_id": knowledge_pack_version_id,
                        },
                    )
                ],
                limit=5_000,
            )
        except SQLAlchemyError:
            abort(500)

        for revision in revisions:
            if revision.status in {"draft", "review"}:
                abort(
                    409,
                    "All revisions must be approved or archived before publishing.",
                )

    async def action_submit_for_review(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: KnowledgePackSubmitForReviewValidation,
    ) -> tuple[dict[str, Any], int]:
        """Submit a draft version for governance review."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "draft":
            abort(409, "Only draft versions can be submitted for review.")

        await self._update_version_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "review",
                "submitted_at": self._now_utc(),
                "submitted_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.note),
            },
        )

        await self._transition_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            from_statuses={"draft"},
            to_status="review",
            actor_user_id=auth_user_id,
        )

        await self._record_approval(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            action="submit_for_review",
            actor_user_id=auth_user_id,
            note=data.note,
        )

        return "", 204

    async def action_approve(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: KnowledgePackApproveValidation,
    ) -> tuple[dict[str, Any], int]:
        """Approve a reviewed version."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "review":
            abort(409, "Only review versions can be approved.")

        await self._update_version_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "approved",
                "approved_at": self._now_utc(),
                "approved_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.note),
            },
        )

        await self._transition_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            from_statuses={"review"},
            to_status="approved",
            actor_user_id=auth_user_id,
        )

        await self._record_approval(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            action="approve",
            actor_user_id=auth_user_id,
            note=data.note,
        )

        return "", 204

    async def action_reject(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: KnowledgePackRejectValidation,
    ) -> tuple[dict[str, Any], int]:
        """Reject a reviewed version back to draft."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "review":
            abort(409, "Only review versions can be rejected.")

        note = self._normalize_optional_text(data.reason or data.note)

        await self._update_version_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "draft",
                "note": note,
            },
        )

        await self._transition_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            from_statuses={"review"},
            to_status="draft",
            actor_user_id=auth_user_id,
        )

        await self._record_approval(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            action="reject",
            actor_user_id=auth_user_id,
            note=note,
        )

        return "", 204

    async def action_publish(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: KnowledgePackPublishValidation,
    ) -> tuple[dict[str, Any], int]:
        """Publish an approved version and archive prior published siblings."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "approved":
            abort(409, "Only approved versions can be published.")

        if current.knowledge_pack_id is None:
            abort(409, "KnowledgePackId is required for publish workflow.")

        await self._validate_no_unreviewed_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
        )

        published_versions = await self._list_pack_versions_by_status(
            tenant_id=tenant_id,
            knowledge_pack_id=current.knowledge_pack_id,
            statuses=["published"],
        )

        for version in published_versions:
            if version.id is None or version.id == entity_id:
                continue

            try:
                await self.update(
                    where={
                        "tenant_id": tenant_id,
                        "id": version.id,
                    },
                    changes={
                        "status": "archived",
                        "archived_at": self._now_utc(),
                        "archived_by_user_id": auth_user_id,
                    },
                )
            except SQLAlchemyError:
                abort(500)

            await self._transition_revisions(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version.id,
                from_statuses={"published"},
                to_status="archived",
                actor_user_id=auth_user_id,
            )

        await self._update_version_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "published",
                "published_at": self._now_utc(),
                "published_by_user_id": auth_user_id,
                "archived_at": None,
                "archived_by_user_id": None,
                "note": self._normalize_optional_text(data.note),
            },
        )

        await self._transition_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            from_statuses={"approved", "archived"},
            to_status="published",
            actor_user_id=auth_user_id,
        )

        await self._set_pack_current_version(
            tenant_id=tenant_id,
            knowledge_pack_id=current.knowledge_pack_id,
            current_version_id=entity_id,
        )

        await self._record_approval(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            action="publish",
            actor_user_id=auth_user_id,
            note=data.note,
        )

        return "", 204

    async def action_archive(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: KnowledgePackArchiveValidation,
    ) -> tuple[dict[str, Any], int]:
        """Archive a version and mark its published revisions archived."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "archived":
            return "", 204

        await self._update_version_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "archived",
                "archived_at": self._now_utc(),
                "archived_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.reason or data.note),
            },
        )

        await self._transition_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            from_statuses={"published", "approved", "review", "draft"},
            to_status="archived",
            actor_user_id=auth_user_id,
        )

        if current.knowledge_pack_id is not None:
            try:
                pack = await self._pack_service.get(
                    {
                        "tenant_id": tenant_id,
                        "id": current.knowledge_pack_id,
                    }
                )
            except SQLAlchemyError:
                abort(500)

            if pack is not None and pack.current_version_id == entity_id:
                await self._set_pack_current_version(
                    tenant_id=tenant_id,
                    knowledge_pack_id=current.knowledge_pack_id,
                    current_version_id=None,
                )

        await self._record_approval(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            action="archive",
            actor_user_id=auth_user_id,
            note=data.reason or data.note,
        )

        return "", 204

    async def action_rollback_version(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: KnowledgePackRollbackVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Republish this historical version and archive current published sibling."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status not in {"archived", "approved", "published"}:
            abort(
                409,
                "Only archived, approved, or published versions can be rolled back.",
            )

        if current.knowledge_pack_id is None:
            abort(409, "KnowledgePackId is required for rollback workflow.")

        await self._validate_no_unreviewed_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
        )

        published_versions = await self._list_pack_versions_by_status(
            tenant_id=tenant_id,
            knowledge_pack_id=current.knowledge_pack_id,
            statuses=["published"],
        )

        rollback_of_version_id: uuid.UUID | None = None
        for version in published_versions:
            if version.id is None or version.id == entity_id:
                continue

            rollback_of_version_id = version.id

            try:
                await self.update(
                    where={
                        "tenant_id": tenant_id,
                        "id": version.id,
                    },
                    changes={
                        "status": "archived",
                        "archived_at": self._now_utc(),
                        "archived_by_user_id": auth_user_id,
                    },
                )
            except SQLAlchemyError:
                abort(500)

            await self._transition_revisions(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version.id,
                from_statuses={"published"},
                to_status="archived",
                actor_user_id=auth_user_id,
            )

        if current.status != "published":
            await self._update_version_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "published",
                    "published_at": self._now_utc(),
                    "published_by_user_id": auth_user_id,
                    "archived_at": None,
                    "archived_by_user_id": None,
                    "rollback_of_version_id": rollback_of_version_id,
                    "note": self._normalize_optional_text(data.note),
                },
            )

        await self._transition_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            from_statuses={"approved", "archived"},
            to_status="published",
            actor_user_id=auth_user_id,
        )

        await self._set_pack_current_version(
            tenant_id=tenant_id,
            knowledge_pack_id=current.knowledge_pack_id,
            current_version_id=entity_id,
        )

        await self._record_approval(
            tenant_id=tenant_id,
            knowledge_pack_version_id=entity_id,
            action="rollback_version",
            actor_user_id=auth_user_id,
            note=data.note,
            payload={
                "rollback_of_version_id": (
                    str(rollback_of_version_id)
                    if rollback_of_version_id is not None
                    else None
                )
            },
        )

        return "", 204
