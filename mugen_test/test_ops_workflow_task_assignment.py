"""Unit tests for ops_workflow task assignment and handoff behavior."""

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAssignTaskValidation,
    WorkflowCompleteTaskValidation,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowTaskDE
from mugen.core.plugin.ops_workflow.service.workflow_task import WorkflowTaskService


class TestOpsWorkflowTaskAssignment(unittest.IsolatedAsyncioTestCase):
    """Tests assignment/handoff behavior on WorkflowTaskService."""

    async def test_assign_task_tracks_handoff_count(self) -> None:
        """Reassignment should increment handoff_count and emit task_assigned."""
        tenant_id = uuid.uuid4()
        task_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        old_owner = uuid.uuid4()
        new_owner = uuid.uuid4()

        svc = WorkflowTaskService(table="ops_workflow_workflow_task", rsg=Mock())

        current = WorkflowTaskDE(
            id=task_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="in_progress",
            assignee_user_id=old_owner,
            queue_name="ops-l2",
            handoff_count=2,
            row_version=8,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="in_progress",
                assignee_user_id=new_owner,
                queue_name="ops-l3",
                handoff_count=3,
                row_version=9,
            )
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        resp = await svc.action_assign_task(
            tenant_id=tenant_id,
            entity_id=task_id,
            where={"tenant_id": tenant_id, "id": task_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowAssignTaskValidation(
                row_version=8,
                assignee_user_id=new_owner,
                queue_name="ops-l3",
            ),
        )

        self.assertEqual(resp, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["handoff_count"], 3)
        self.assertEqual(changes["queue_name"], "ops-l3")

        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "task_assigned")
        self.assertEqual(event_payload["payload"]["handoff_count"], 3)

    async def test_complete_task_sets_completion_fields(self) -> None:
        """Completing a task should set terminal fields and emit task_completed."""
        tenant_id = uuid.uuid4()
        task_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        svc = WorkflowTaskService(table="ops_workflow_workflow_task", rsg=Mock())

        svc.get = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="in_progress",
                row_version=3,
            )
        )
        svc.update_with_row_version = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="completed",
                row_version=4,
            )
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        resp = await svc.action_complete_task(
            tenant_id=tenant_id,
            entity_id=task_id,
            where={"tenant_id": tenant_id, "id": task_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowCompleteTaskValidation(row_version=3, outcome="done"),
        )

        self.assertEqual(resp, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "completed")
        self.assertEqual(changes["outcome"], "done")
        self.assertIsNotNone(changes["completed_at"])

        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "task_completed")
        self.assertEqual(event_payload["payload"]["outcome"], "done")

    async def test_assign_task_rejects_terminal_task(self) -> None:
        """Terminal tasks cannot be reassigned."""
        tenant_id = uuid.uuid4()
        task_id = uuid.uuid4()

        svc = WorkflowTaskService(table="ops_workflow_workflow_task", rsg=Mock())
        svc.get = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=uuid.uuid4(),
                status="completed",
                row_version=2,
            )
        )
        svc.update_with_row_version = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_assign_task(
                tenant_id=tenant_id,
                entity_id=task_id,
                where={"tenant_id": tenant_id, "id": task_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowAssignTaskValidation(
                    row_version=2,
                    queue_name="ops-l1",
                ),
            )

        self.assertEqual(ctx.exception.code, 409)
        svc.update_with_row_version.assert_not_called()
