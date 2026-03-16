"""Unit tests for knowledge_pack KnowledgePackVersionService edge branches."""

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.knowledge_pack.api.validation import (
    KnowledgePackApproveValidation,
    KnowledgePackArchiveValidation,
    KnowledgePackPublishValidation,
    KnowledgePackRejectValidation,
    KnowledgePackRollbackVersionValidation,
    KnowledgePackSubmitForReviewValidation,
)
from mugen.core.plugin.knowledge_pack.domain import (
    KnowledgeEntryRevisionDE,
    KnowledgePackDE,
    KnowledgePackVersionDE,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_pack_version import (
    KnowledgePackVersionService,
)


class TestKnowledgePackVersionServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Covers helper, guard, and SQL-error branches for version workflow."""

    def _svc(self) -> KnowledgePackVersionService:
        return KnowledgePackVersionService(
            table="knowledge_pack_knowledge_pack_version",
            rsg=Mock(),
        )

    async def test_get_for_action_raises_500_on_primary_sql_error(self) -> None:
        svc = self._svc()
        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where={"id": uuid.uuid4()}, expected_row_version=1
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_get_for_action_raises_500_when_base_lookup_fails(self) -> None:
        svc = self._svc()
        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where={"id": uuid.uuid4()}, expected_row_version=1
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_get_for_action_raises_404_and_409_for_missing_or_conflict(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=3)
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[
                None,
                KnowledgePackVersionDE(id=version_id, tenant_id=tenant_id),
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=3)
        self.assertEqual(ctx.exception.code, 409)

    async def test_update_version_with_row_version_raises_for_conflict_sql_and_none(
        self,
    ) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("knowledge_pack_knowledge_pack_version")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_version_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "review"},
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_version_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "review"},
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_version_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "review"},
            )
        self.assertEqual(ctx.exception.code, 404)

    async def test_record_approval_raises_500_on_sql_error(self) -> None:
        svc = self._svc()
        svc._approval_service.create = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc._record_approval(
                tenant_id=uuid.uuid4(),
                knowledge_pack_version_id=uuid.uuid4(),
                action="approve",
                actor_user_id=uuid.uuid4(),
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_list_pack_versions_by_status_handles_empty_and_sql_error(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()

        self.assertEqual(
            await svc._list_pack_versions_by_status(
                tenant_id=tenant_id,
                knowledge_pack_id=pack_id,
                statuses=[],
            ),
            [],
        )

        svc.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._list_pack_versions_by_status(
                tenant_id=tenant_id,
                knowledge_pack_id=pack_id,
                statuses=["published"],
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_set_pack_current_version_raises_500_on_sql_error(self) -> None:
        svc = self._svc()
        svc._pack_service.update = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc._set_pack_current_version(
                tenant_id=uuid.uuid4(),
                knowledge_pack_id=uuid.uuid4(),
                current_version_id=uuid.uuid4(),
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_transition_revisions_handles_skips_and_archive_changes(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        matched_id = uuid.uuid4()

        svc._revision_service.list = AsyncMock(
            return_value=[
                KnowledgeEntryRevisionDE(
                    id=None, tenant_id=tenant_id, status="published"
                ),
                KnowledgeEntryRevisionDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    status="draft",
                ),
                KnowledgeEntryRevisionDE(
                    id=matched_id,
                    tenant_id=tenant_id,
                    status="published",
                ),
            ]
        )
        svc._revision_service.update = AsyncMock(return_value=Mock())

        await svc._transition_revisions(
            tenant_id=tenant_id,
            knowledge_pack_version_id=version_id,
            from_statuses={"published"},
            to_status="archived",
            actor_user_id=actor_id,
        )

        self.assertEqual(svc._revision_service.update.await_count, 1)
        update_kwargs = svc._revision_service.update.await_args.kwargs
        self.assertEqual(update_kwargs["where"]["id"], matched_id)
        self.assertEqual(update_kwargs["changes"]["status"], "archived")
        self.assertEqual(update_kwargs["changes"]["archived_by_user_id"], actor_id)

    async def test_transition_revisions_raises_500_on_list_or_update_errors(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc._revision_service.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._transition_revisions(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
                from_statuses={"published"},
                to_status="archived",
                actor_user_id=actor_id,
            )
        self.assertEqual(ctx.exception.code, 500)

        svc._revision_service.list = AsyncMock(
            return_value=[
                KnowledgeEntryRevisionDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    status="published",
                )
            ]
        )
        svc._revision_service.update = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._transition_revisions(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
                from_statuses={"published"},
                to_status="archived",
                actor_user_id=actor_id,
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_validate_no_unreviewed_revisions_raises_on_sql_or_open_status(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()

        svc._revision_service.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._validate_no_unreviewed_revisions(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
            )
        self.assertEqual(ctx.exception.code, 500)

        svc._revision_service.list = AsyncMock(
            return_value=[KnowledgeEntryRevisionDE(status="draft")]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._validate_no_unreviewed_revisions(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_action_status_guards_for_submit_approve_reject_and_publish(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(status="review")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_submit_for_review(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackSubmitForReviewValidation(row_version=1),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(status="draft")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_approve(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackApproveValidation(row_version=1),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(status="approved")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_reject(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackRejectValidation(row_version=1),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(status="draft")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_publish(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackPublishValidation(row_version=1),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_action_publish_rejects_missing_pack_id(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(
                id=version_id,
                tenant_id=tenant_id,
                status="approved",
                knowledge_pack_id=None,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_publish(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackPublishValidation(row_version=2),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_action_publish_skips_invalid_published_siblings(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        current = KnowledgePackVersionDE(
            id=version_id,
            tenant_id=tenant_id,
            knowledge_pack_id=pack_id,
            status="approved",
            row_version=3,
        )
        svc._get_for_action = AsyncMock(return_value=current)
        svc._validate_no_unreviewed_revisions = AsyncMock(return_value=None)
        svc._list_pack_versions_by_status = AsyncMock(
            return_value=[
                KnowledgePackVersionDE(
                    id=None, tenant_id=tenant_id, status="published"
                ),
                KnowledgePackVersionDE(
                    id=version_id, tenant_id=tenant_id, status="published"
                ),
            ]
        )
        svc.update = AsyncMock(return_value=Mock())
        svc._update_version_with_row_version = AsyncMock(return_value=current)
        svc._transition_revisions = AsyncMock(return_value=None)
        svc._set_pack_current_version = AsyncMock(return_value=None)
        svc._record_approval = AsyncMock(return_value=None)

        result = await svc.action_publish(
            tenant_id=tenant_id,
            entity_id=version_id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=KnowledgePackPublishValidation(row_version=3),
        )

        self.assertEqual(result, ("", 204))
        svc.update.assert_not_called()

    async def test_action_publish_raises_500_when_sibling_archive_fails(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        sibling_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        current = KnowledgePackVersionDE(
            id=version_id,
            tenant_id=tenant_id,
            knowledge_pack_id=pack_id,
            status="approved",
            row_version=4,
        )
        svc._get_for_action = AsyncMock(return_value=current)
        svc._validate_no_unreviewed_revisions = AsyncMock(return_value=None)
        svc._list_pack_versions_by_status = AsyncMock(
            return_value=[KnowledgePackVersionDE(id=sibling_id, status="published")]
        )
        svc.update = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_publish(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackPublishValidation(row_version=4),
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_action_archive_returns_204_when_already_archived(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(
                id=version_id,
                tenant_id=tenant_id,
                status="archived",
                row_version=1,
            )
        )
        svc._update_version_with_row_version = AsyncMock(return_value=Mock())

        result = await svc.action_archive(
            tenant_id=tenant_id,
            entity_id=version_id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=KnowledgePackArchiveValidation(row_version=1),
        )

        self.assertEqual(result, ("", 204))
        svc._update_version_with_row_version.assert_not_called()

    async def test_action_archive_clears_pack_current_version_when_entity_matches(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        current = KnowledgePackVersionDE(
            id=version_id,
            tenant_id=tenant_id,
            knowledge_pack_id=pack_id,
            status="published",
            row_version=2,
        )
        svc._get_for_action = AsyncMock(return_value=current)
        svc._update_version_with_row_version = AsyncMock(return_value=current)
        svc._transition_revisions = AsyncMock(return_value=None)
        svc._pack_service.get = AsyncMock(
            return_value=KnowledgePackDE(
                id=pack_id,
                tenant_id=tenant_id,
                current_version_id=version_id,
            )
        )
        svc._set_pack_current_version = AsyncMock(return_value=None)
        svc._record_approval = AsyncMock(return_value=None)

        result = await svc.action_archive(
            tenant_id=tenant_id,
            entity_id=version_id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=KnowledgePackArchiveValidation(row_version=2, reason="cleanup"),
        )

        self.assertEqual(result, ("", 204))
        svc._set_pack_current_version.assert_awaited_once()

    async def test_action_archive_raises_500_on_pack_lookup_failure(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(
                id=version_id,
                tenant_id=tenant_id,
                knowledge_pack_id=pack_id,
                status="approved",
                row_version=3,
            )
        )
        svc._update_version_with_row_version = AsyncMock(return_value=Mock())
        svc._transition_revisions = AsyncMock(return_value=None)
        svc._pack_service.get = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_archive(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackArchiveValidation(row_version=3),
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_action_archive_skips_pack_lookup_when_version_has_no_pack_id(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(
                id=version_id,
                tenant_id=tenant_id,
                knowledge_pack_id=None,
                status="published",
                row_version=3,
            )
        )
        svc._update_version_with_row_version = AsyncMock(return_value=Mock())
        svc._transition_revisions = AsyncMock(return_value=None)
        svc._pack_service.get = AsyncMock(return_value=Mock())
        svc._set_pack_current_version = AsyncMock(return_value=None)
        svc._record_approval = AsyncMock(return_value=None)

        result = await svc.action_archive(
            tenant_id=tenant_id,
            entity_id=version_id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=KnowledgePackArchiveValidation(row_version=3),
        )

        self.assertEqual(result, ("", 204))
        svc._pack_service.get.assert_not_awaited()
        svc._set_pack_current_version.assert_not_awaited()

    async def test_action_archive_does_not_clear_pack_when_current_version_differs(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(
                id=version_id,
                tenant_id=tenant_id,
                knowledge_pack_id=pack_id,
                status="published",
                row_version=4,
            )
        )
        svc._update_version_with_row_version = AsyncMock(return_value=Mock())
        svc._transition_revisions = AsyncMock(return_value=None)
        svc._pack_service.get = AsyncMock(
            return_value=KnowledgePackDE(
                id=pack_id,
                tenant_id=tenant_id,
                current_version_id=uuid.uuid4(),
            )
        )
        svc._set_pack_current_version = AsyncMock(return_value=None)
        svc._record_approval = AsyncMock(return_value=None)

        result = await svc.action_archive(
            tenant_id=tenant_id,
            entity_id=version_id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=KnowledgePackArchiveValidation(row_version=4, reason=" ", note=" note "),
        )

        self.assertEqual(result, ("", 204))
        svc._set_pack_current_version.assert_not_awaited()
        update_kwargs = svc._update_version_with_row_version.await_args.kwargs
        self.assertEqual(update_kwargs["changes"]["note"], "note")
        approval_kwargs = svc._record_approval.await_args.kwargs
        self.assertEqual(approval_kwargs["note"], "note")

    async def test_action_rollback_rejects_invalid_status(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(status="draft")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_rollback_version(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackRollbackVersionValidation(row_version=1),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_action_rollback_rejects_missing_pack_id(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(
                status="approved", knowledge_pack_id=None
            )
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_rollback_version(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackRollbackVersionValidation(row_version=1),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_action_rollback_archives_sibling_and_promotes_current(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        sibling_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        current = KnowledgePackVersionDE(
            id=version_id,
            tenant_id=tenant_id,
            knowledge_pack_id=pack_id,
            status="approved",
            row_version=7,
        )
        svc._get_for_action = AsyncMock(return_value=current)
        svc._validate_no_unreviewed_revisions = AsyncMock(return_value=None)
        svc._list_pack_versions_by_status = AsyncMock(
            return_value=[
                KnowledgePackVersionDE(id=None, status="published"),
                KnowledgePackVersionDE(id=version_id, status="published"),
                KnowledgePackVersionDE(id=sibling_id, status="published"),
            ]
        )
        svc.update = AsyncMock(return_value=Mock())
        svc._transition_revisions = AsyncMock(return_value=None)
        svc._update_version_with_row_version = AsyncMock(return_value=current)
        svc._set_pack_current_version = AsyncMock(return_value=None)
        svc._record_approval = AsyncMock(return_value=None)

        result = await svc.action_rollback_version(
            tenant_id=tenant_id,
            entity_id=version_id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=KnowledgePackRollbackVersionValidation(row_version=7),
        )

        self.assertEqual(result, ("", 204))
        self.assertEqual(svc.update.await_count, 1)
        sibling_archive = svc.update.await_args.kwargs["changes"]
        self.assertEqual(sibling_archive["status"], "archived")
        rollback_changes = svc._update_version_with_row_version.await_args.kwargs[
            "changes"
        ]
        self.assertEqual(rollback_changes["rollback_of_version_id"], sibling_id)

    async def test_action_rollback_raises_500_when_sibling_archive_fails(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        sibling_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(
                id=version_id,
                tenant_id=tenant_id,
                knowledge_pack_id=pack_id,
                status="approved",
                row_version=8,
            )
        )
        svc._validate_no_unreviewed_revisions = AsyncMock(return_value=None)
        svc._list_pack_versions_by_status = AsyncMock(
            return_value=[KnowledgePackVersionDE(id=sibling_id, status="published")]
        )
        svc.update = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_rollback_version(
                tenant_id=tenant_id,
                entity_id=version_id,
                where=where,
                auth_user_id=uuid.uuid4(),
                data=KnowledgePackRollbackVersionValidation(row_version=8),
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_action_rollback_skips_publish_update_when_already_published(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": version_id}

        svc._get_for_action = AsyncMock(
            return_value=KnowledgePackVersionDE(
                id=version_id,
                tenant_id=tenant_id,
                knowledge_pack_id=pack_id,
                status="published",
                row_version=9,
            )
        )
        svc._validate_no_unreviewed_revisions = AsyncMock(return_value=None)
        svc._list_pack_versions_by_status = AsyncMock(return_value=[])
        svc._update_version_with_row_version = AsyncMock(return_value=Mock())
        svc._transition_revisions = AsyncMock(return_value=None)
        svc._set_pack_current_version = AsyncMock(return_value=None)
        svc._record_approval = AsyncMock(return_value=None)

        result = await svc.action_rollback_version(
            tenant_id=tenant_id,
            entity_id=version_id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=KnowledgePackRollbackVersionValidation(row_version=9),
        )

        self.assertEqual(result, ("", 204))
        svc._update_version_with_row_version.assert_not_called()
