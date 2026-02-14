"""Unit tests for ops_workflow WorkflowTaskService edge branches."""

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAssignTaskValidation,
    WorkflowCompleteTaskValidation,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowTaskDE
from mugen.core.plugin.ops_workflow.service.workflow_task import WorkflowTaskService


class TestWorkflowTaskServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Covers helper and guard branches not hit by lifecycle tests."""

    def _svc(self) -> WorkflowTaskService:
        return WorkflowTaskService(table="ops_workflow_workflow_task", rsg=Mock())

    async def test_get_for_action_raises_500_on_sql_error(self) -> None:
        svc = self._svc()
        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where={"id": uuid.uuid4()}, expected_row_version=1
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_get_for_action_raises_404_and_409_for_missing_or_conflict(
        self,
    ) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=2)
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[
                None,
                WorkflowTaskDE(id=where["id"], tenant_id=where["tenant_id"]),
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=2)
        self.assertEqual(ctx.exception.code, 409)

    async def test_get_for_action_raises_500_when_base_lookup_fails(self) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=3)

        self.assertEqual(ctx.exception.code, 500)

    async def test_update_task_with_row_version_raises_for_conflict_sql_and_none(
        self,
    ) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_workflow_workflow_task")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_task_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "in_progress"},
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_task_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "in_progress"},
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_task_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "in_progress"},
            )
        self.assertEqual(ctx.exception.code, 404)

    async def test_assign_task_does_not_increment_handoff_when_target_unchanged(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        task_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        svc = self._svc()
        current = WorkflowTaskDE(
            id=task_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="in_progress",
            assignee_user_id=owner_id,
            queue_name="ops-l1",
            handoff_count=3,
            row_version=4,
        )
        updated = WorkflowTaskDE(
            id=task_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="in_progress",
            assignee_user_id=owner_id,
            queue_name="ops-l1",
            handoff_count=3,
            row_version=5,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=updated)
        svc._event_service.create = AsyncMock(return_value=Mock())

        result = await svc.action_assign_task(
            tenant_id=tenant_id,
            entity_id=task_id,
            where={"tenant_id": tenant_id, "id": task_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowAssignTaskValidation(
                row_version=4,
                assignee_user_id=owner_id,
                queue_name="ops-l1",
            ),
        )

        self.assertEqual(result, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["handoff_count"], 3)

    async def test_assign_task_skips_event_when_updated_task_lacks_identifiers(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        task_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        svc = self._svc()
        svc.get = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=uuid.uuid4(),
                status="open",
                row_version=1,
            )
        )
        svc.update_with_row_version = AsyncMock(
            return_value=WorkflowTaskDE(
                id=None,
                tenant_id=tenant_id,
                workflow_instance_id=None,
                status="in_progress",
            )
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        result = await svc.action_assign_task(
            tenant_id=tenant_id,
            entity_id=task_id,
            where={"tenant_id": tenant_id, "id": task_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowAssignTaskValidation(
                row_version=1,
                assignee_user_id=owner_id,
            ),
        )

        self.assertEqual(result, ("", 204))
        svc._event_service.create.assert_not_called()

    async def test_complete_task_rejects_terminal_status(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        task_id = uuid.uuid4()
        svc.get = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                status="completed",
                row_version=2,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_complete_task(
                tenant_id=tenant_id,
                entity_id=task_id,
                where={"tenant_id": tenant_id, "id": task_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowCompleteTaskValidation(row_version=2),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_complete_task_skips_event_when_updated_task_lacks_identifiers(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        task_id = uuid.uuid4()

        svc = self._svc()
        svc.get = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=uuid.uuid4(),
                status="in_progress",
                row_version=2,
            )
        )
        svc.update_with_row_version = AsyncMock(
            return_value=WorkflowTaskDE(
                id=None,
                tenant_id=tenant_id,
                workflow_instance_id=None,
                status="completed",
                row_version=3,
            )
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        result = await svc.action_complete_task(
            tenant_id=tenant_id,
            entity_id=task_id,
            where={"tenant_id": tenant_id, "id": task_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowCompleteTaskValidation(row_version=2, outcome="done"),
        )

        self.assertEqual(result, ("", 204))
        svc._event_service.create.assert_not_called()
