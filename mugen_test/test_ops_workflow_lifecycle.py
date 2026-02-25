"""Unit tests for ops_workflow instance transition and approval behavior."""

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAdvanceValidation,
    WorkflowApproveValidation,
    WorkflowRejectValidation,
)
from mugen.core.plugin.ops_workflow.domain import (
    WorkflowDecisionRequestDE,
    WorkflowInstanceDE,
    WorkflowStateDE,
    WorkflowTaskDE,
    WorkflowTransitionDE,
)
from mugen.core.plugin.ops_workflow.service.workflow_instance import (
    WorkflowInstanceService,
)


class TestOpsWorkflowLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests lifecycle and approval paths on WorkflowInstanceService."""

    async def test_advance_rejects_missing_transition(self) -> None:
        """Advance should fail when no deterministic transition exists."""
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )

        svc.get = AsyncMock(
            return_value=WorkflowInstanceDE(
                id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=uuid.uuid4(),
                current_state_id=uuid.uuid4(),
                status="active",
                row_version=4,
            )
        )
        svc._transition_service.list = AsyncMock(return_value=[])
        svc.update_with_row_version = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_advance(
                tenant_id=tenant_id,
                entity_id=instance_id,
                where={"tenant_id": tenant_id, "id": instance_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowAdvanceValidation(row_version=4, transition_key="next"),
            )

        self.assertEqual(ctx.exception.code, 409)
        svc.update_with_row_version.assert_not_called()

    async def test_advance_with_approval_creates_pending_task(self) -> None:
        """Advance should create approval task and set awaiting_approval status."""
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        transition_id = uuid.uuid4()
        task_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )

        current = WorkflowInstanceDE(
            id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=uuid.uuid4(),
            current_state_id=uuid.uuid4(),
            status="active",
            row_version=3,
        )

        svc.get = AsyncMock(return_value=current)
        svc._transition_service.list = AsyncMock(
            return_value=[
                WorkflowTransitionDE(
                    id=transition_id,
                    tenant_id=tenant_id,
                    workflow_version_id=current.workflow_version_id,
                    key="manager_approval",
                    from_state_id=current.current_state_id,
                    to_state_id=uuid.uuid4(),
                    requires_approval=True,
                )
            ]
        )
        svc._task_service.create = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            )
        )
        svc._decision_request_service.action_open = AsyncMock(
            return_value=({"DecisionRequestId": str(uuid.uuid4())}, 201)
        )
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._event_service.create = AsyncMock(return_value=Mock())

        resp = await svc.action_advance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where={"tenant_id": tenant_id, "id": instance_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowAdvanceValidation(
                row_version=3,
                transition_key="manager_approval",
            ),
        )

        self.assertEqual(resp, ("", 204))
        svc._task_service.create.assert_awaited_once()
        svc.update_with_row_version.assert_awaited_once()
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "awaiting_approval")
        self.assertEqual(changes["pending_transition_id"], transition_id)
        self.assertEqual(changes["pending_task_id"], task_id)
        svc._decision_request_service.action_open.assert_awaited_once()

        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "approval_requested")

    async def test_advance_open_failure_reconcile_does_not_revert_progressed_state(
        self,
    ) -> None:
        """Open failure should reconcile as success when instance already progressed."""
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        transition_id = uuid.uuid4()
        task_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        state_id = uuid.uuid4()
        to_state_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )

        current = WorkflowInstanceDE(
            id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=uuid.uuid4(),
            current_state_id=state_id,
            status="active",
            row_version=4,
        )
        transition = WorkflowTransitionDE(
            id=transition_id,
            tenant_id=tenant_id,
            workflow_version_id=current.workflow_version_id,
            key="manager_approval",
            from_state_id=current.current_state_id,
            to_state_id=to_state_id,
            requires_approval=True,
        )
        pending_instance = WorkflowInstanceDE(
            id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=current.workflow_version_id,
            current_state_id=state_id,
            pending_transition_id=transition_id,
            pending_task_id=task_id,
            status="awaiting_approval",
            row_version=5,
        )
        progressed_instance = WorkflowInstanceDE(
            id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=current.workflow_version_id,
            current_state_id=to_state_id,
            status="active",
            row_version=6,
        )

        svc._get_for_action = AsyncMock(return_value=current)
        svc._resolve_transition = AsyncMock(return_value=transition)
        svc._task_service.create = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="open",
                row_version=1,
            )
        )
        svc._update_instance_with_row_version = AsyncMock(return_value=pending_instance)
        svc._decision_request_service.action_open = AsyncMock(
            side_effect=RuntimeError("decision open failed")
        )
        svc._find_open_decision_request = AsyncMock(return_value=None)
        svc.get = AsyncMock(return_value=progressed_instance)
        svc.update_with_row_version = AsyncMock()
        svc._task_service.update_with_row_version = AsyncMock()

        resp = await svc.action_advance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where={"tenant_id": tenant_id, "id": instance_id},
            auth_user_id=actor_id,
            data=WorkflowAdvanceValidation(
                row_version=4,
                transition_key="manager_approval",
            ),
        )

        self.assertEqual(resp, ("", 204))
        svc.update_with_row_version.assert_not_awaited()
        svc._task_service.update_with_row_version.assert_not_awaited()

    async def test_approve_applies_transition_and_completes_task(self) -> None:
        """Approve should complete pending task and advance to target state."""
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        transition_id = uuid.uuid4()
        task_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )

        current = WorkflowInstanceDE(
            id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=uuid.uuid4(),
            current_state_id=uuid.uuid4(),
            pending_transition_id=transition_id,
            pending_task_id=task_id,
            status="awaiting_approval",
            row_version=9,
        )

        svc.get = AsyncMock(return_value=current)
        svc._transition_service.get = AsyncMock(
            return_value=WorkflowTransitionDE(
                id=transition_id,
                tenant_id=tenant_id,
                workflow_version_id=current.workflow_version_id,
                key="manager_approval",
                from_state_id=current.current_state_id,
                to_state_id=state_id,
                requires_approval=True,
            )
        )
        svc._task_service.get = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="open",
                row_version=4,
            )
        )
        svc._task_service.update_with_row_version = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="completed",
                row_version=5,
            )
        )
        decision_request_id = uuid.uuid4()
        svc._get_or_create_legacy_decision_request = AsyncMock(
            return_value=(
                WorkflowDecisionRequestDE(
                    id=decision_request_id,
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    workflow_task_id=task_id,
                    status="open",
                    row_version=6,
                ),
                True,
            )
        )
        svc._decision_request_service.action_resolve = AsyncMock(
            return_value=({"DecisionRequestId": str(uuid.uuid4())}, 200)
        )
        svc._state_service.get = AsyncMock(
            return_value=WorkflowStateDE(
                id=state_id,
                tenant_id=tenant_id,
                workflow_version_id=current.workflow_version_id,
                key="approved",
                is_terminal=False,
            )
        )
        svc.update_with_row_version = AsyncMock(
            return_value=WorkflowInstanceDE(
                id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=current.workflow_version_id,
                current_state_id=state_id,
                status="active",
                row_version=10,
            )
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        resp = await svc.action_approve(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where={"tenant_id": tenant_id, "id": instance_id},
            auth_user_id=actor_id,
            data=WorkflowApproveValidation(row_version=9),
        )

        self.assertEqual(resp, ("", 204))
        svc._task_service.update_with_row_version.assert_awaited_once()
        task_changes = svc._task_service.update_with_row_version.await_args.kwargs[
            "changes"
        ]
        self.assertEqual(task_changes["status"], "completed")
        self.assertEqual(task_changes["outcome"], "approved")

        instance_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(instance_changes["status"], "active")
        self.assertEqual(instance_changes["current_state_id"], state_id)

        event_types = [
            call.args[0]["event_type"]
            for call in svc._event_service.create.await_args_list
        ]
        self.assertEqual(event_types, ["task_completed", "approved"])
        approved_payload = svc._event_service.create.await_args_list[-1].args[0][
            "payload"
        ]
        self.assertEqual(
            approved_payload["decision_request_id"],
            str(decision_request_id),
        )
        self.assertTrue(approved_payload["legacy_bridge_created"])

    async def test_reject_clears_pending_transition(self) -> None:
        """Reject should keep current state and clear pending transition/task ids."""
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        task_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )

        current_state_id = uuid.uuid4()
        current = WorkflowInstanceDE(
            id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=uuid.uuid4(),
            current_state_id=current_state_id,
            pending_transition_id=uuid.uuid4(),
            pending_task_id=task_id,
            status="awaiting_approval",
            row_version=5,
        )

        svc.get = AsyncMock(return_value=current)
        svc._task_service.get = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="open",
                row_version=2,
            )
        )
        svc._task_service.update_with_row_version = AsyncMock(
            return_value=WorkflowTaskDE(
                id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="rejected",
                row_version=3,
            )
        )
        decision_request_id = uuid.uuid4()
        svc._get_or_create_legacy_decision_request = AsyncMock(
            return_value=(
                WorkflowDecisionRequestDE(
                    id=decision_request_id,
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    workflow_task_id=task_id,
                    status="open",
                    row_version=4,
                ),
                True,
            )
        )
        svc._decision_request_service.action_cancel = AsyncMock(
            return_value=({"DecisionRequestId": str(uuid.uuid4())}, 200)
        )
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._event_service.create = AsyncMock(return_value=Mock())

        resp = await svc.action_reject(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where={"tenant_id": tenant_id, "id": instance_id},
            auth_user_id=actor_id,
            data=WorkflowRejectValidation(row_version=5, reason="insufficient data"),
        )

        self.assertEqual(resp, ("", 204))
        instance_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(instance_changes["status"], "active")
        self.assertIsNone(instance_changes["pending_transition_id"])
        self.assertIsNone(instance_changes["pending_task_id"])

        event_types = [
            call.args[0]["event_type"]
            for call in svc._event_service.create.await_args_list
        ]
        self.assertEqual(event_types, ["task_completed", "rejected"])
        rejected_payload = svc._event_service.create.await_args_list[-1].args[0][
            "payload"
        ]
        self.assertEqual(
            rejected_payload["decision_request_id"],
            str(decision_request_id),
        )
        self.assertTrue(rejected_payload["legacy_bridge_created"])
