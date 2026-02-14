"""Unit tests for knowledge_pack workflow, scope filtering, and immutability."""

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.knowledge_pack.api.validation import (
    KnowledgePackApproveValidation,
    KnowledgePackPublishValidation,
    KnowledgePackRejectValidation,
    KnowledgePackRollbackVersionValidation,
    KnowledgePackSubmitForReviewValidation,
)
from mugen.core.plugin.knowledge_pack.domain import (
    KnowledgeEntryRevisionDE,
    KnowledgePackVersionDE,
    KnowledgeScopeDE,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_entry_revision import (
    KnowledgeEntryRevisionService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_pack_version import (
    KnowledgePackVersionService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_scope import (
    KnowledgeScopeService,
)


class TestKnowledgePackLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests version workflow and scoped retrieval behavior."""

    async def test_submit_reject_and_approve_transitions(self) -> None:
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = KnowledgePackVersionService(
            table="knowledge_pack_knowledge_pack_version",
            rsg=Mock(),
        )

        current = KnowledgePackVersionDE(
            id=version_id,
            tenant_id=tenant_id,
            knowledge_pack_id=uuid.uuid4(),
            status="draft",
            row_version=3,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._revision_service.list = AsyncMock(
            side_effect=[
                [
                    KnowledgeEntryRevisionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        status="draft",
                    )
                ],
                [
                    KnowledgeEntryRevisionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        status="review",
                    )
                ],
                [
                    KnowledgeEntryRevisionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        status="review",
                    )
                ],
            ]
        )
        svc._revision_service.update = AsyncMock(return_value=Mock())
        svc._approval_service.create = AsyncMock(return_value=Mock())

        submit_result = await svc.action_submit_for_review(
            tenant_id=tenant_id,
            entity_id=version_id,
            where={"tenant_id": tenant_id, "id": version_id},
            auth_user_id=actor_id,
            data=KnowledgePackSubmitForReviewValidation(row_version=3),
        )
        self.assertEqual(submit_result, ("", 204))

        submit_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(submit_changes["status"], "review")

        current.status = "review"
        current.row_version = 4

        reject_result = await svc.action_reject(
            tenant_id=tenant_id,
            entity_id=version_id,
            where={"tenant_id": tenant_id, "id": version_id},
            auth_user_id=actor_id,
            data=KnowledgePackRejectValidation(row_version=4, reason="needs edits"),
        )
        self.assertEqual(reject_result, ("", 204))

        reject_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(reject_changes["status"], "draft")

        current.status = "review"
        current.row_version = 5

        approve_result = await svc.action_approve(
            tenant_id=tenant_id,
            entity_id=version_id,
            where={"tenant_id": tenant_id, "id": version_id},
            auth_user_id=actor_id,
            data=KnowledgePackApproveValidation(row_version=5),
        )
        self.assertEqual(approve_result, ("", 204))

        approve_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(approve_changes["status"], "approved")

    async def test_publish_archives_current_published_sibling(self) -> None:
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        sibling_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = KnowledgePackVersionService(
            table="knowledge_pack_knowledge_pack_version",
            rsg=Mock(),
        )

        current = KnowledgePackVersionDE(
            id=version_id,
            tenant_id=tenant_id,
            knowledge_pack_id=pack_id,
            status="approved",
            row_version=8,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc.list = AsyncMock(
            return_value=[
                KnowledgePackVersionDE(
                    id=sibling_id,
                    tenant_id=tenant_id,
                    knowledge_pack_id=pack_id,
                    status="published",
                )
            ]
        )
        svc.update = AsyncMock(return_value=Mock())
        svc._pack_service.update = AsyncMock(return_value=Mock())
        svc._approval_service.create = AsyncMock(return_value=Mock())

        revision_id = uuid.uuid4()
        svc._revision_service.list = AsyncMock(
            side_effect=[
                [
                    KnowledgeEntryRevisionDE(
                        id=revision_id,
                        tenant_id=tenant_id,
                        status="approved",
                    )
                ],
                [],
                [
                    KnowledgeEntryRevisionDE(
                        id=revision_id,
                        tenant_id=tenant_id,
                        status="approved",
                    )
                ],
            ]
        )
        svc._revision_service.update = AsyncMock(return_value=Mock())

        result = await svc.action_publish(
            tenant_id=tenant_id,
            entity_id=version_id,
            where={"tenant_id": tenant_id, "id": version_id},
            auth_user_id=actor_id,
            data=KnowledgePackPublishValidation(row_version=8),
        )

        self.assertEqual(result, ("", 204))
        publish_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(publish_changes["status"], "published")

        archive_sibling_changes = svc.update.await_args.kwargs["changes"]
        self.assertEqual(archive_sibling_changes["status"], "archived")

        pack_changes = svc._pack_service.update.await_args.kwargs["changes"]
        self.assertEqual(pack_changes["current_version_id"], version_id)

    async def test_rollback_promotes_archived_version(self) -> None:
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = KnowledgePackVersionService(
            table="knowledge_pack_knowledge_pack_version",
            rsg=Mock(),
        )

        current = KnowledgePackVersionDE(
            id=version_id,
            tenant_id=tenant_id,
            knowledge_pack_id=pack_id,
            status="archived",
            row_version=2,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc.list = AsyncMock(return_value=[])
        svc.update = AsyncMock(return_value=Mock())
        svc._pack_service.update = AsyncMock(return_value=Mock())
        svc._approval_service.create = AsyncMock(return_value=Mock())
        svc._revision_service.list = AsyncMock(
            side_effect=[
                [
                    KnowledgeEntryRevisionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        status="approved",
                    )
                ],
                [
                    KnowledgeEntryRevisionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        status="approved",
                    )
                ],
            ]
        )
        svc._revision_service.update = AsyncMock(return_value=Mock())

        result = await svc.action_rollback_version(
            tenant_id=tenant_id,
            entity_id=version_id,
            where={"tenant_id": tenant_id, "id": version_id},
            auth_user_id=actor_id,
            data=KnowledgePackRollbackVersionValidation(row_version=2),
        )

        self.assertEqual(result, ("", 204))
        rollback_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(rollback_changes["status"], "published")

    async def test_scope_filtering_returns_only_published_revisions(self) -> None:
        tenant_id = uuid.uuid4()

        published_revision_id = uuid.uuid4()
        non_published_revision_id = uuid.uuid4()

        scope_svc = KnowledgeScopeService(
            table="knowledge_pack_knowledge_scope",
            rsg=Mock(),
        )

        scope_svc.list = AsyncMock(
            return_value=[
                KnowledgeScopeDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=uuid.uuid4(),
                    knowledge_entry_revision_id=published_revision_id,
                    channel="chat",
                    locale="en-US",
                    category="billing",
                    is_active=True,
                ),
                KnowledgeScopeDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=uuid.uuid4(),
                    knowledge_entry_revision_id=non_published_revision_id,
                    channel="chat",
                    locale="en-US",
                    category="billing",
                    is_active=True,
                ),
            ]
        )

        scope_svc._version_service.get = AsyncMock(
            side_effect=[
                KnowledgePackVersionDE(status="published"),
                KnowledgePackVersionDE(status="draft"),
            ]
        )
        scope_svc._revision_service.get = AsyncMock(
            side_effect=[
                KnowledgeEntryRevisionDE(status="published"),
                KnowledgeEntryRevisionDE(status="published"),
            ]
        )
        scope_svc._revision_service.list = AsyncMock(
            return_value=[
                KnowledgeEntryRevisionDE(
                    id=published_revision_id,
                    tenant_id=tenant_id,
                    status="published",
                )
            ]
        )

        revisions = await scope_svc.list_published_revisions(
            tenant_id=tenant_id,
            channel="chat",
            locale="en-US",
            category="billing",
        )

        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].id, published_revision_id)

    async def test_published_revision_is_immutable(self) -> None:
        tenant_id = uuid.uuid4()
        revision_id = uuid.uuid4()

        svc = KnowledgeEntryRevisionService(
            table="knowledge_pack_knowledge_entry_revision",
            rsg=Mock(),
        )

        svc.get = AsyncMock(
            return_value=KnowledgeEntryRevisionDE(
                id=revision_id,
                tenant_id=tenant_id,
                status="published",
                row_version=3,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.update_with_row_version(
                where={"tenant_id": tenant_id, "id": revision_id},
                expected_row_version=3,
                changes={"body": "updated"},
            )

        self.assertEqual(ctx.exception.code, 409)
