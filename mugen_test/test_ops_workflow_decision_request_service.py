"""Unit tests for ops_workflow WorkflowDecisionRequestService."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowDecisionRequestCancelValidation,
    WorkflowDecisionRequestExpireOverdueValidation,
    WorkflowDecisionRequestOpenValidation,
    WorkflowDecisionRequestResolveValidation,
)
from mugen.core.plugin.ops_workflow.domain import (
    WorkflowDecisionOutcomeDE,
    WorkflowDecisionRequestDE,
)
from mugen.core.plugin.ops_workflow.service.workflow_decision_request import (
    WorkflowDecisionRequestService,
)


class TestOpsWorkflowDecisionRequestService(unittest.IsolatedAsyncioTestCase):
    """Covers decision request open/resolve/cancel/expire_overdue actions."""

    @staticmethod
    def _svc() -> WorkflowDecisionRequestService:
        return WorkflowDecisionRequestService(
            table="ops_workflow_decision_request",
            rsg=Mock(),
        )

    async def test_open_creates_request_and_emits_event(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        task_id = uuid.uuid4()
        request_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc.create = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=request_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                workflow_task_id=task_id,
                template_key="workflow.approval",
                status="open",
                row_version=1,
            )
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        response, status = await svc.action_open(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=WorkflowDecisionRequestOpenValidation(
                template_key="workflow.approval",
                workflow_instance_id=instance_id,
                workflow_task_id=task_id,
                trace_id="trace-123",
                note="approval required",
            ),
        )

        self.assertEqual(status, 201)
        self.assertEqual(response["DecisionRequestId"], str(request_id))
        create_payload = svc.create.await_args.args[0]
        self.assertEqual(create_payload["template_key"], "workflow.approval")
        self.assertEqual(create_payload["trace_id"], "trace-123")

        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "decision_opened")
        self.assertEqual(event_payload["workflow_instance_id"], instance_id)
        self.assertEqual(event_payload["workflow_task_id"], task_id)

    async def test_resolve_appends_outcome_and_marks_resolved(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        request_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        task_id = uuid.uuid4()

        current = WorkflowDecisionRequestDE(
            id=request_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            workflow_task_id=task_id,
            status="open",
            row_version=3,
        )
        updated = WorkflowDecisionRequestDE(
            id=request_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            workflow_task_id=task_id,
            status="resolved",
            row_version=4,
        )
        outcome = WorkflowDecisionOutcomeDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            decision_request_id=request_id,
        )
        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=updated)
        svc._outcome_service.create = AsyncMock(return_value=outcome)
        svc._event_service.create = AsyncMock(return_value=Mock())

        response, status = await svc.action_resolve(
            tenant_id=tenant_id,
            entity_id=request_id,
            where={"tenant_id": tenant_id, "id": request_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowDecisionRequestResolveValidation(
                row_version=3,
                outcome="approved",
                reason="manager approved",
                note="approved",
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["Status"], "resolved")
        self.assertEqual(response["DecisionRequestId"], str(request_id))

        update_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(update_changes["status"], "resolved")
        self.assertIsNotNone(update_changes["resolved_at"])

        outcome_payload = svc._outcome_service.create.await_args.args[0]
        self.assertEqual(outcome_payload["decision_request_id"], request_id)

        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "decision_resolved")

    async def test_cancel_marks_request_cancelled(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        request_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        current = WorkflowDecisionRequestDE(
            id=request_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="open",
            row_version=2,
        )
        updated = WorkflowDecisionRequestDE(
            id=request_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="cancelled",
            row_version=3,
        )
        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=updated)
        svc._event_service.create = AsyncMock(return_value=Mock())

        response, status = await svc.action_cancel(
            tenant_id=tenant_id,
            entity_id=request_id,
            where={"tenant_id": tenant_id, "id": request_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowDecisionRequestCancelValidation(
                row_version=2,
                reason="workflow rejected",
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["Status"], "cancelled")
        self.assertEqual(response["DecisionRequestId"], str(request_id))
        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "decision_cancelled")

    async def test_expire_overdue_expires_due_rows_and_skips_conflicts(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        now = datetime(2026, 2, 25, 18, 0, tzinfo=timezone.utc)
        instance_id = uuid.uuid4()
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()

        first = WorkflowDecisionRequestDE(
            id=first_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="open",
            row_version=3,
            due_at=now,
        )
        second = WorkflowDecisionRequestDE(
            id=second_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="open",
            row_version=4,
            due_at=now,
        )
        updated_first = WorkflowDecisionRequestDE(
            id=first_id,
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="expired",
            row_version=4,
        )

        svc.list = AsyncMock(return_value=[first, second])
        svc.update_with_row_version = AsyncMock(
            side_effect=[
                updated_first,
                RowVersionConflict("ops_workflow_decision_request"),
            ]
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        response, status = await svc.action_expire_overdue(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=uuid.uuid4(),
            data=WorkflowDecisionRequestExpireOverdueValidation(
                as_of_utc=now,
                limit=100,
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["ExpiredCount"], 1)
        self.assertEqual(response["ExpiredIds"], [str(first_id)])
        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "decision_expired")

    async def test_resolve_rejects_non_open_state(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        request_id = uuid.uuid4()
        svc.get = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=request_id,
                tenant_id=tenant_id,
                status="cancelled",
                row_version=2,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_resolve(
                tenant_id=tenant_id,
                entity_id=request_id,
                where={"tenant_id": tenant_id, "id": request_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowDecisionRequestResolveValidation(
                    row_version=2,
                    outcome="approved",
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

    def test_internal_helpers_cover_constraint_and_time_parsing(self) -> None:
        svc = self._svc()

        class _Diag:
            constraint_name = "  ux_custom  "

        class _Orig:
            diag = _Diag()

        err_with_diag = IntegrityError("insert", {}, Exception("boom"))
        err_with_diag.orig = _Orig()
        self.assertEqual(
            svc._integrity_constraint_name(err_with_diag),  # pylint: disable=protected-access
            "ux_custom",
        )

        err_with_event_name = IntegrityError(
            "insert",
            {},
            Exception(
                "duplicate key value violates unique constraint "
                "ux_ops_wf_event_tenant_instance_event_seq"
            ),
        )
        self.assertEqual(
            svc._integrity_constraint_name(err_with_event_name),  # pylint: disable=protected-access
            svc._EVENT_SEQ_UNIQUE_CONSTRAINT,  # pylint: disable=protected-access
        )
        self.assertTrue(
            svc._is_event_seq_conflict(err_with_event_name)  # pylint: disable=protected-access
        )

        err_with_outcome_name = IntegrityError(
            "insert",
            {},
            Exception(
                "duplicate key value violates unique constraint "
                "ux_ops_wf_decision_outcome_tenant_request"
            ),
        )
        self.assertEqual(
            svc._integrity_constraint_name(err_with_outcome_name),  # pylint: disable=protected-access
            svc._OUTCOME_UNIQUE_CONSTRAINT,  # pylint: disable=protected-access
        )
        self.assertTrue(
            svc._is_outcome_unique_conflict(err_with_outcome_name)  # pylint: disable=protected-access
        )

        unknown_err = IntegrityError("insert", {}, Exception("other"))
        self.assertIsNone(
            svc._integrity_constraint_name(unknown_err)  # pylint: disable=protected-access
        )

        self.assertEqual(
            svc._to_aware_utc(datetime(2026, 2, 25, 20, 0)),  # pylint: disable=protected-access
            datetime(2026, 2, 25, 20, 0, tzinfo=timezone.utc),
        )

    async def test_internal_next_seq_and_append_event_error_paths(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        svc._event_seq_cache[(tenant_id, instance_id)] = 4
        self.assertEqual(
            await svc._next_event_seq(  # pylint: disable=protected-access
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            ),
            5,
        )

        svc._event_seq_cache = {}
        svc._event_service.list = AsyncMock(return_value=[Mock(event_seq=8)])
        svc._event_service.count = AsyncMock(return_value=0)
        self.assertEqual(
            await svc._next_event_seq(  # pylint: disable=protected-access
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            ),
            9,
        )

        svc._event_seq_cache = {}
        svc._event_service.list = AsyncMock(return_value=[])
        svc._event_service.count = AsyncMock(return_value=2)
        self.assertEqual(
            await svc._next_event_seq(  # pylint: disable=protected-access
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            ),
            3,
        )

        svc._event_seq_cache = {}
        svc._event_service.list = AsyncMock(side_effect=RuntimeError("boom"))
        self.assertEqual(
            await svc._next_event_seq(  # pylint: disable=protected-access
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            ),
            1,
        )

        request_without_context = WorkflowDecisionRequestDE(
            id=uuid.uuid4(),
            tenant_id=None,
            workflow_instance_id=None,
            status="open",
            row_version=1,
        )
        svc._event_service.create = AsyncMock()
        await svc._append_event(  # pylint: disable=protected-access
            decision_request=request_without_context,
            event_type="decision_opened",
            actor_user_id=uuid.uuid4(),
        )
        svc._event_service.create.assert_not_awaited()

        failing_request = WorkflowDecisionRequestDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="open",
            row_version=1,
        )
        svc._event_seq_cache[(tenant_id, instance_id)] = 1
        svc._event_service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("random integrity"))
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._append_event(  # pylint: disable=protected-access
                decision_request=failing_request,
                event_type="decision_opened",
                actor_user_id=uuid.uuid4(),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc._event_service.create = AsyncMock(side_effect=SQLAlchemyError("db boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._append_event(  # pylint: disable=protected-access
                decision_request=failing_request,
                event_type="decision_opened",
                actor_user_id=uuid.uuid4(),
            )
        self.assertEqual(ctx.exception.code, 500)

        seq_conflict = IntegrityError(
            "insert",
            {"event_seq": 2},
            Exception(
                "duplicate key value violates unique constraint "
                "ux_ops_wf_event_tenant_instance_event_seq"
            ),
        )
        svc._event_service.create = AsyncMock(
            side_effect=[
                seq_conflict,
                seq_conflict,
                seq_conflict,
                seq_conflict,
                seq_conflict,
            ]
        )
        svc._event_service.list = AsyncMock(return_value=[Mock(event_seq=1)])
        svc._event_service.count = AsyncMock(return_value=0)
        with self.assertRaises(HTTPException) as ctx:
            await svc._append_event(  # pylint: disable=protected-access
                decision_request=failing_request,
                event_type="decision_opened",
                actor_user_id=uuid.uuid4(),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc._EVENT_APPEND_MAX_ATTEMPTS = 0  # pylint: disable=protected-access
        svc._event_service.create = AsyncMock()
        await svc._append_event(  # pylint: disable=protected-access
            decision_request=failing_request,
            event_type="decision_opened",
            actor_user_id=uuid.uuid4(),
        )
        svc._event_service.create.assert_not_awaited()

    async def test_internal_get_and_update_row_version_error_paths(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        request_id = uuid.uuid4()

        svc.get = AsyncMock(side_effect=SQLAlchemyError("lookup failed"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(  # pylint: disable=protected-access
                where={"tenant_id": tenant_id, "id": request_id},
                expected_row_version=1,
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("base failed")])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(  # pylint: disable=protected-access
                where={"tenant_id": tenant_id, "id": request_id},
                expected_row_version=1,
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(  # pylint: disable=protected-access
                where={"tenant_id": tenant_id, "id": request_id},
                expected_row_version=1,
            )
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[
                None,
                WorkflowDecisionRequestDE(
                    id=request_id,
                    tenant_id=tenant_id,
                    status="open",
                    row_version=2,
                ),
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(  # pylint: disable=protected-access
                where={"tenant_id": tenant_id, "id": request_id},
                expected_row_version=1,
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_workflow_decision_request")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(  # pylint: disable=protected-access
                where={"tenant_id": tenant_id, "id": request_id},
                expected_row_version=1,
                changes={"status": "resolved"},
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("update"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(  # pylint: disable=protected-access
                where={"tenant_id": tenant_id, "id": request_id},
                expected_row_version=1,
                changes={"status": "resolved"},
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(  # pylint: disable=protected-access
                where={"tenant_id": tenant_id, "id": request_id},
                expected_row_version=1,
                changes={"status": "resolved"},
            )
        self.assertEqual(ctx.exception.code, 404)

    async def test_action_open_and_resolve_error_paths(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        request_id = uuid.uuid4()

        svc.create = AsyncMock(side_effect=SQLAlchemyError("create"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_open(
                tenant_id=tenant_id,
                where={"tenant_id": tenant_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowDecisionRequestOpenValidation(template_key="workflow.approval"),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.create = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=None,
                tenant_id=tenant_id,
                status="open",
                row_version=1,
            )
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_open(
                tenant_id=tenant_id,
                where={"tenant_id": tenant_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowDecisionRequestOpenValidation(template_key="workflow.approval"),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=None,
                tenant_id=tenant_id,
                status="open",
                row_version=1,
            )
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_resolve(
                tenant_id=tenant_id,
                entity_id=request_id,
                where={"tenant_id": tenant_id, "id": request_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowDecisionRequestResolveValidation(
                    row_version=1,
                    outcome="approved",
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        current = WorkflowDecisionRequestDE(
            id=request_id,
            tenant_id=tenant_id,
            status="open",
            row_version=3,
        )
        updated = WorkflowDecisionRequestDE(
            id=request_id,
            tenant_id=tenant_id,
            status="resolved",
            row_version=4,
        )
        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=updated)
        svc._outcome_service.create = AsyncMock(
            side_effect=IntegrityError(
                "insert",
                {},
                Exception(
                    "duplicate key value violates unique constraint "
                    "ux_ops_wf_decision_outcome_tenant_request"
                ),
            )
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_resolve(
                tenant_id=tenant_id,
                entity_id=request_id,
                where={"tenant_id": tenant_id, "id": request_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowDecisionRequestResolveValidation(
                    row_version=3,
                    outcome="approved",
                    attributes={"k": "v"},
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc._outcome_service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("other"))
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_resolve(
                tenant_id=tenant_id,
                entity_id=request_id,
                where={"tenant_id": tenant_id, "id": request_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowDecisionRequestResolveValidation(
                    row_version=3,
                    outcome="approved",
                ),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc._outcome_service.create = AsyncMock(side_effect=SQLAlchemyError("write"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_resolve(
                tenant_id=tenant_id,
                entity_id=request_id,
                where={"tenant_id": tenant_id, "id": request_id},
                auth_user_id=uuid.uuid4(),
                data=WorkflowDecisionRequestResolveValidation(
                    row_version=3,
                    outcome="approved",
                ),
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_cancel_and_expire_error_paths(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        request_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc.get = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=request_id,
                tenant_id=tenant_id,
                status="resolved",
                row_version=2,
            )
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_cancel(
                tenant_id=tenant_id,
                entity_id=request_id,
                where={"tenant_id": tenant_id, "id": request_id},
                auth_user_id=actor_id,
                data=WorkflowDecisionRequestCancelValidation(row_version=2),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.list = AsyncMock(side_effect=SQLAlchemyError("list failed"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_expire_overdue(
                tenant_id=tenant_id,
                where={"tenant_id": tenant_id},
                auth_user_id=actor_id,
                data=WorkflowDecisionRequestExpireOverdueValidation(limit=5),
            )
        self.assertEqual(ctx.exception.code, 500)

        idless = WorkflowDecisionRequestDE(
            id=None,
            tenant_id=tenant_id,
            status="open",
            row_version=2,
            due_at=datetime(2026, 2, 25, 18, 0, tzinfo=timezone.utc),
        )
        invalid_row_version = WorkflowDecisionRequestDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            status="open",
            row_version=0,
            due_at=datetime(2026, 2, 25, 18, 0, tzinfo=timezone.utc),
        )
        updatable = WorkflowDecisionRequestDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            status="open",
            row_version=5,
            due_at=datetime(2026, 2, 25, 18, 0, tzinfo=timezone.utc),
        )
        svc.list = AsyncMock(return_value=[idless, invalid_row_version, updatable])
        svc.update_with_row_version = AsyncMock(return_value=None)
        response, status = await svc.action_expire_overdue(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=WorkflowDecisionRequestExpireOverdueValidation(limit=10),
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["ExpiredCount"], 0)

        svc.list = AsyncMock(return_value=[updatable])
        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("update"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_expire_overdue(
                tenant_id=tenant_id,
                where={"tenant_id": tenant_id},
                auth_user_id=actor_id,
                data=WorkflowDecisionRequestExpireOverdueValidation(limit=10),
            )
        self.assertEqual(ctx.exception.code, 500)
