"""Branch coverage tests for ops_workflow WorkflowInstanceService."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_governance.domain import PolicyDefinitionDE
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAdvanceValidation,
    WorkflowApproveValidation,
    WorkflowCompensateValidation,
    WorkflowCancelInstanceValidation,
    WorkflowReplayValidation,
    WorkflowRejectValidation,
    WorkflowStartInstanceValidation,
)
from mugen.core.plugin.ops_workflow.domain import (
    WorkflowActionDedupDE,
    WorkflowDecisionRequestDE,
    WorkflowEventDE,
    WorkflowInstanceDE,
    WorkflowStateDE,
    WorkflowTaskDE,
    WorkflowTransitionDE,
)
from mugen.core.plugin.ops_workflow.service import workflow_instance as workflow_mod
from mugen.core.plugin.ops_workflow.service.workflow_instance import (
    WorkflowInstanceService,
)


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _instance(
    *,
    instance_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    workflow_version_id: uuid.UUID | None = None,
    current_state_id: uuid.UUID | None = None,
    pending_transition_id: uuid.UUID | None = None,
    pending_task_id: uuid.UUID | None = None,
    status: str = "draft",
    row_version: int = 1,
    started_at: datetime | None = None,
) -> WorkflowInstanceDE:
    return WorkflowInstanceDE(
        id=instance_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        workflow_version_id=workflow_version_id,
        current_state_id=current_state_id,
        pending_transition_id=pending_transition_id,
        pending_task_id=pending_task_id,
        status=status,
        row_version=row_version,
        started_at=started_at,
    )


def _state(
    *,
    state_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    workflow_version_id: uuid.UUID | None = None,
    is_initial: bool | None = None,
    is_terminal: bool | None = None,
) -> WorkflowStateDE:
    return WorkflowStateDE(
        id=state_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        workflow_version_id=workflow_version_id,
        is_initial=is_initial,
        is_terminal=is_terminal,
    )


def _transition(
    *,
    transition_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    workflow_version_id: uuid.UUID | None = None,
    from_state_id: uuid.UUID | None = None,
    to_state_id: uuid.UUID | None = None,
    key: str | None = "next",
    requires_approval: bool | None = False,
    auto_assign_user_id: uuid.UUID | None = None,
    auto_assign_queue: str | None = None,
) -> WorkflowTransitionDE:
    return WorkflowTransitionDE(
        id=transition_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        workflow_version_id=workflow_version_id,
        from_state_id=from_state_id,
        to_state_id=to_state_id,
        key=key,
        requires_approval=requires_approval,
        auto_assign_user_id=auto_assign_user_id,
        auto_assign_queue=auto_assign_queue,
    )


def _task(
    *,
    task_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    workflow_instance_id: uuid.UUID | None = None,
    status: str | None = "open",
    row_version: int | None = 1,
) -> WorkflowTaskDE:
    return WorkflowTaskDE(
        id=task_id,
        tenant_id=tenant_id,
        workflow_instance_id=workflow_instance_id,
        status=status,
        row_version=row_version,
    )


class TestMugenOpsWorkflowWorkflowInstanceService(unittest.IsolatedAsyncioTestCase):
    """Covers helper and action edge branches not exercised by lifecycle tests."""

    async def test_normalize_append_event_and_create_branches(self) -> None:
        now = datetime(2026, 2, 14, 17, 0, tzinfo=timezone.utc)
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        state_id = uuid.uuid4()

        rsg = Mock()
        rsg.insert_one = AsyncMock(
            return_value={
                "id": instance_id,
                "tenant_id": tenant_id,
                "current_state_id": state_id,
                "status": "draft",
            }
        )
        svc = WorkflowInstanceService(table="ops_workflow_workflow_instance", rsg=rsg)
        svc._now_utc = Mock(return_value=now)
        svc._event_service.create = AsyncMock()

        self.assertIsNone(WorkflowInstanceService._normalize_optional_text(None))
        self.assertIsNone(WorkflowInstanceService._normalize_optional_text(" "))
        self.assertEqual(WorkflowInstanceService._normalize_optional_text(" ok "), "ok")

        created = await svc.create({"tenant_id": tenant_id, "status": "draft"})
        self.assertEqual(created.id, instance_id)
        self.assertEqual(svc._event_service.create.await_count, 1)
        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "created")
        self.assertEqual(event_payload["occurred_at"], now)

        rsg.insert_one = AsyncMock(return_value={"id": None, "tenant_id": tenant_id})
        svc._event_service.create = AsyncMock()
        created_without_id = await svc.create({"tenant_id": tenant_id})
        self.assertIsNone(created_without_id.id)
        svc._event_service.create.assert_not_awaited()

        await svc._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            event_type="manual",
            actor_user_id=None,
            from_state_id=None,
            to_state_id=state_id,
            note="  ",
            payload=None,
        )
        payload = svc._event_service.create.await_args.args[0]
        self.assertIsNone(payload["note"])
        self.assertIsNone(payload["payload"])

    async def test_append_event_retries_sequence_conflict_then_succeeds(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        state_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        svc._event_seq_cache[(tenant_id, instance_id)] = 9
        svc._event_service.list = AsyncMock(return_value=[WorkflowEventDE(event_seq=10)])
        svc._event_service.count = AsyncMock(return_value=0)
        svc._event_service.create = AsyncMock(
            side_effect=[
                IntegrityError(
                    "insert",
                    {"event_seq": 10},
                    Exception(
                        (
                            "duplicate key value violates unique constraint "
                            '"ux_ops_wf_event_tenant_instance_event_seq"'
                        )
                    ),
                ),
                WorkflowEventDE(id=uuid.uuid4()),
            ]
        )

        await svc._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            event_type="advanced",
            actor_user_id=None,
            from_state_id=state_id,
            to_state_id=state_id,
        )

        self.assertEqual(svc._event_service.create.await_count, 2)
        first_event_seq = svc._event_service.create.await_args_list[0].args[0]["event_seq"]
        second_event_seq = svc._event_service.create.await_args_list[1].args[0][
            "event_seq"
        ]
        self.assertEqual(first_event_seq, 10)
        self.assertEqual(second_event_seq, 11)
        self.assertEqual(svc._event_seq_cache[(tenant_id, instance_id)], 11)
        svc._event_service.list.assert_awaited_once()

    async def test_append_event_conflicts_exhausted_returns_409(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        svc._event_seq_cache[(tenant_id, instance_id)] = 5
        svc._event_service.list = AsyncMock(return_value=[WorkflowEventDE(event_seq=5)])
        svc._event_service.count = AsyncMock(return_value=0)
        seq_conflict = IntegrityError(
            "insert",
            {"event_seq": 6},
            Exception(
                (
                    "duplicate key value violates unique constraint "
                    '"ux_ops_wf_event_tenant_instance_event_seq"'
                )
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

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._append_event(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    event_type="advanced",
                    actor_user_id=None,
                    from_state_id=None,
                    to_state_id=None,
                )
            self.assertEqual(ex.exception.code, 409)

        self.assertEqual(svc._event_service.create.await_count, 5)

    async def test_append_event_non_sequence_integrity_error_returns_500(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        svc._event_service.list = AsyncMock(return_value=[WorkflowEventDE(event_seq=1)])
        svc._event_service.count = AsyncMock(return_value=0)
        svc._event_service.create = AsyncMock(
            side_effect=IntegrityError(
                "insert",
                {"event_seq": 2},
                Exception(
                    'duplicate key value violates unique constraint "ux_other_constraint"'
                ),
            )
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._append_event(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    event_type="advanced",
                    actor_user_id=None,
                    from_state_id=None,
                    to_state_id=None,
                )
            self.assertEqual(ex.exception.code, 500)

    def test_integrity_constraint_name_prefers_diag_constraint_name(self) -> None:
        orig = Exception("duplicate")
        orig.diag = type(  # type: ignore[attr-defined]
            "Diag",
            (),
            {"constraint_name": "ux_ops_wf_event_tenant_instance_event_seq"},
        )()
        error = IntegrityError("insert", {"event_seq": 1}, orig)

        self.assertEqual(
            WorkflowInstanceService._integrity_constraint_name(error),
            "ux_ops_wf_event_tenant_instance_event_seq",
        )

    async def test_append_event_with_zero_max_attempts_noops(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        svc._EVENT_APPEND_MAX_ATTEMPTS = 0
        svc._event_service.create = AsyncMock()

        await svc._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            event_type="advanced",
            actor_user_id=None,
            from_state_id=None,
            to_state_id=None,
        )

        svc._event_service.create.assert_not_awaited()

    async def test_append_event_sqlalchemy_error_returns_500(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        svc._event_service.list = AsyncMock(return_value=[WorkflowEventDE(event_seq=1)])
        svc._event_service.count = AsyncMock(return_value=0)
        svc._event_service.create = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._append_event(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    event_type="advanced",
                    actor_user_id=None,
                    from_state_id=None,
                    to_state_id=None,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_get_update_and_resolver_helper_branches(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        version_id = uuid.uuid4()
        state_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        current = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            current_state_id=state_id,
            status="active",
            row_version=5,
        )

        svc.get = AsyncMock(return_value=current)
        self.assertEqual(
            (await svc._get_for_action(where=where, expected_row_version=5)).id,
            instance_id,
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=5)
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, None])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=5)
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(side_effect=[None, current])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=5)
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=5)
            self.assertEqual(ex.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=current)
        self.assertEqual(
            (
                await svc._update_instance_with_row_version(
                    where=where,
                    expected_row_version=5,
                    changes={"status": "active"},
                )
            ).id,
            instance_id,
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("ops_workflow_workflow_instance", where)
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_instance_with_row_version(
                    where=where,
                    expected_row_version=5,
                    changes={"status": "active"},
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_instance_with_row_version(
                    where=where,
                    expected_row_version=5,
                    changes={"status": "active"},
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_instance_with_row_version(
                    where=where,
                    expected_row_version=5,
                    changes={"status": "active"},
                )
            self.assertEqual(ex.exception.code, 404)

        initial = _state(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            is_initial=True,
        )
        svc._state_service.get = AsyncMock(return_value=initial)
        self.assertEqual(
            (
                await svc._resolve_initial_state(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    start_state_id=initial.id,
                )
            ).id,
            initial.id,
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc._state_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_initial_state(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    start_state_id=uuid.uuid4(),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._state_service.list = AsyncMock(return_value=[])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_initial_state(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    start_state_id=None,
                )
            self.assertEqual(ex.exception.code, 409)

            svc._state_service.list = AsyncMock(return_value=[initial, initial])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_initial_state(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    start_state_id=None,
                )
            self.assertEqual(ex.exception.code, 409)

            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_transition(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    from_state_id=state_id,
                    transition_key=" ",
                    to_state_id=None,
                )
            self.assertEqual(ex.exception.code, 400)

            svc._transition_service.list = AsyncMock(return_value=[])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_transition(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    from_state_id=state_id,
                    transition_key="next",
                    to_state_id=None,
                )
            self.assertEqual(ex.exception.code, 409)

            svc._transition_service.list = AsyncMock(
                return_value=[_transition(), _transition()]
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_transition(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    from_state_id=state_id,
                    transition_key="next",
                    to_state_id=None,
                )
            self.assertEqual(ex.exception.code, 409)

            svc._state_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_state(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    state_id=uuid.uuid4(),
                )
            self.assertEqual(ex.exception.code, 409)

        svc._state_service.list = AsyncMock(return_value=[initial])
        self.assertEqual(
            (
                await svc._resolve_initial_state(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    start_state_id=None,
                )
            ).id,
            initial.id,
        )

        next_transition = _transition(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            to_state_id=uuid.uuid4(),
            key="next",
        )
        svc._transition_service.list = AsyncMock(return_value=[next_transition])
        resolved_transition = await svc._resolve_transition(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            transition_key=" next ",
            to_state_id=next_transition.to_state_id,
        )
        self.assertEqual(resolved_transition.id, next_transition.id)
        where_resolve = svc._transition_service.list.await_args.kwargs["filter_groups"][
            0
        ].where
        self.assertEqual(where_resolve["key"], "next")
        self.assertEqual(where_resolve["to_state_id"], next_transition.to_state_id)

        resolved_state = _state(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
        )
        svc._state_service.get = AsyncMock(return_value=resolved_state)
        self.assertEqual(
            (
                await svc._resolve_state(
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    state_id=resolved_state.id,
                )
            ).id,
            resolved_state.id,
        )

    async def test_update_pending_task_and_apply_transition_branches(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 17, 30, tzinfo=timezone.utc)

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_pending_task(
                    task=_task(
                        task_id=None,
                        tenant_id=tenant_id,
                        workflow_instance_id=instance_id,
                        row_version=2,
                    ),
                    status="completed",
                    outcome="approved",
                    actor_user_id=actor_id,
                    now=now,
                )
            self.assertEqual(ex.exception.code, 409)

            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_pending_task(
                    task=_task(
                        task_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        workflow_instance_id=instance_id,
                        row_version=0,
                    ),
                    status="completed",
                    outcome="approved",
                    actor_user_id=actor_id,
                    now=now,
                )
            self.assertEqual(ex.exception.code, 409)

            svc._task_service.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("ops_workflow_workflow_task")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_pending_task(
                    task=_task(
                        task_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        workflow_instance_id=instance_id,
                        row_version=2,
                    ),
                    status="completed",
                    outcome="approved",
                    actor_user_id=actor_id,
                    now=now,
                )
            self.assertEqual(ex.exception.code, 409)

            svc._task_service.update_with_row_version = AsyncMock(
                side_effect=SQLAlchemyError("boom")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_pending_task(
                    task=_task(
                        task_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        workflow_instance_id=instance_id,
                        row_version=2,
                    ),
                    status="completed",
                    outcome="approved",
                    actor_user_id=actor_id,
                    now=now,
                )
            self.assertEqual(ex.exception.code, 500)

            svc._task_service.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_pending_task(
                    task=_task(
                        task_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        workflow_instance_id=instance_id,
                        row_version=2,
                    ),
                    status="completed",
                    outcome="approved",
                    actor_user_id=actor_id,
                    now=now,
                )
            self.assertEqual(ex.exception.code, 404)

            missing_to_state_transition = _transition(to_state_id=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._apply_transition(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where={"tenant_id": tenant_id, "id": instance_id},
                    current=_instance(
                        instance_id=instance_id,
                        tenant_id=tenant_id,
                        workflow_version_id=uuid.uuid4(),
                        current_state_id=uuid.uuid4(),
                        status="active",
                        row_version=5,
                    ),
                    expected_row_version=5,
                    transition=missing_to_state_transition,
                    auth_user_id=actor_id,
                    event_type="advanced",
                    note=None,
                )
            self.assertEqual(ex.exception.code, 409)

        success_task = _task(
            task_id=uuid.uuid4(),
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            row_version=2,
        )
        svc._task_service.update_with_row_version = AsyncMock(return_value=success_task)
        updated_task = await svc._update_pending_task(
            task=success_task,
            status="cancelled",
            outcome="cancelled",
            actor_user_id=actor_id,
            now=now,
        )
        self.assertEqual(updated_task.id, success_task.id)
        task_changes = svc._task_service.update_with_row_version.await_args.kwargs[
            "changes"
        ]
        self.assertEqual(task_changes["cancelled_at"], now)
        self.assertEqual(task_changes["outcome"], "cancelled")

        current = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=uuid.uuid4(),
            current_state_id=uuid.uuid4(),
            status="active",
            row_version=5,
        )
        terminal_state = _state(
            tenant_id=tenant_id,
            workflow_version_id=current.workflow_version_id,
            is_terminal=True,
        )
        svc._resolve_state = AsyncMock(return_value=terminal_state)
        svc._update_instance_with_row_version = AsyncMock()
        svc._append_event = AsyncMock()
        svc._now_utc = Mock(return_value=now)

        result = await svc._apply_transition(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where={"tenant_id": tenant_id, "id": instance_id},
            current=current,
            expected_row_version=5,
            transition=_transition(
                tenant_id=tenant_id,
                workflow_version_id=current.workflow_version_id,
                from_state_id=current.current_state_id,
                to_state_id=terminal_state.id,
                requires_approval=False,
            ),
            auth_user_id=actor_id,
            event_type="approved",
            note="done",
            payload={"key": "next"},
        )
        self.assertEqual(result, ("", 204))
        instance_changes = svc._update_instance_with_row_version.await_args.kwargs[
            "changes"
        ]
        self.assertEqual(instance_changes["status"], "completed")
        self.assertEqual(instance_changes["completed_at"], now)

    async def test_action_start_and_advance_branches(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        version_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}
        now = datetime(2026, 2, 14, 18, 0, tzinfo=timezone.utc)

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        svc._now_utc = Mock(return_value=now)

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    current_state_id=state_id,
                    status="active",
                    row_version=4,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_start_instance(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowStartInstanceValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=None,
                    current_state_id=None,
                    status="draft",
                    row_version=4,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_start_instance(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowStartInstanceValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

        draft_with_start_time = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            current_state_id=None,
            status="draft",
            row_version=4,
            started_at=datetime(2026, 2, 13, 1, 0, tzinfo=timezone.utc),
        )
        svc._get_for_action = AsyncMock(return_value=draft_with_start_time)
        svc._resolve_initial_state = AsyncMock(
            return_value=_state(
                state_id=state_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                is_initial=True,
            )
        )
        svc._update_instance_with_row_version = AsyncMock()
        svc._append_event = AsyncMock()
        result = await svc.action_start_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowStartInstanceValidation(row_version=4, note="go"),
        )
        self.assertEqual(result, ("", 204))
        start_changes = svc._update_instance_with_row_version.await_args.kwargs[
            "changes"
        ]
        self.assertEqual(start_changes["status"], "active")
        self.assertEqual(start_changes["started_at"], draft_with_start_time.started_at)

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    current_state_id=state_id,
                    status="draft",
                    row_version=6,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_advance(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowAdvanceValidation(
                        row_version=6, transition_key="next"
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=None,
                    current_state_id=None,
                    status="active",
                    row_version=6,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_advance(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowAdvanceValidation(
                        row_version=6, transition_key="next"
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

        active = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            current_state_id=state_id,
            status="active",
            row_version=7,
        )
        transition_with_assignment = _transition(
            transition_id=uuid.uuid4(),
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            to_state_id=uuid.uuid4(),
            requires_approval=True,
            auto_assign_queue="ops-l2",
            key="manager_approval",
        )
        svc._get_for_action = AsyncMock(return_value=active)
        svc._resolve_transition = AsyncMock(return_value=transition_with_assignment)
        svc._task_service.create = AsyncMock(
            return_value=_task(
                task_id=uuid.uuid4(),
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="open",
                row_version=1,
            )
        )
        svc._decision_request_service.action_open = AsyncMock(
            return_value=({"DecisionRequestId": str(uuid.uuid4())}, 201)
        )
        svc._update_instance_with_row_version = AsyncMock()
        svc._append_event = AsyncMock()

        result = await svc.action_advance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowAdvanceValidation(
                row_version=7,
                transition_key="manager_approval",
                task_title="  ",
                task_description="   ",
            ),
        )
        self.assertEqual(result, ("", 204))
        event_types = [
            call.kwargs["event_type"] for call in svc._append_event.await_args_list
        ]
        self.assertEqual(event_types, ["approval_requested", "task_assigned"])

        non_approval_transition = _transition(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            to_state_id=uuid.uuid4(),
            requires_approval=False,
            key="auto",
        )
        svc._resolve_transition = AsyncMock(return_value=non_approval_transition)
        svc._apply_transition = AsyncMock(return_value=("", 204))
        result = await svc.action_advance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowAdvanceValidation(row_version=7, transition_key="auto"),
        )
        self.assertEqual(result, ("", 204))
        svc._apply_transition.assert_awaited_once()

    async def test_action_approve_reject_cancel_branches(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        transition_id = uuid.uuid4()
        task_id = uuid.uuid4()
        state_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc._get_for_action = AsyncMock(
                return_value=_instance(status="active", row_version=3)
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_approve(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowApproveValidation(row_version=3),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_instance(
                    status="awaiting_approval",
                    row_version=3,
                    pending_transition_id=None,
                    pending_task_id=None,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_approve(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowApproveValidation(row_version=3),
                )
            self.assertEqual(ex.exception.code, 409)

            awaiting = _instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=uuid.uuid4(),
                current_state_id=state_id,
                status="awaiting_approval",
                row_version=3,
                pending_transition_id=transition_id,
                pending_task_id=task_id,
            )
            svc._get_for_action = AsyncMock(return_value=awaiting)
            svc._transition_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_approve(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowApproveValidation(row_version=3),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._transition_service.get = AsyncMock(
                return_value=_transition(
                    transition_id=transition_id,
                    tenant_id=tenant_id,
                    workflow_version_id=awaiting.workflow_version_id,
                    from_state_id=state_id,
                    to_state_id=uuid.uuid4(),
                    key="approval",
                    requires_approval=True,
                )
            )
            svc._task_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_approve(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowApproveValidation(row_version=3),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._task_service.get = AsyncMock(
                return_value=_task(
                    task_id=task_id,
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    status="completed",
                    row_version=2,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_approve(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowApproveValidation(row_version=3),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_instance(status="active", row_version=4)
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_reject(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowRejectValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_instance(
                    status="awaiting_approval",
                    row_version=4,
                    pending_task_id=None,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_reject(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowRejectValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

            rejecting_without_task = _instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=uuid.uuid4(),
                current_state_id=state_id,
                status="awaiting_approval",
                row_version=4,
                pending_task_id=task_id,
            )
            svc._get_for_action = AsyncMock(return_value=rejecting_without_task)
            svc._task_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_reject(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowRejectValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._task_service.get = AsyncMock(
                return_value=_task(
                    task_id=task_id,
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    status="completed",
                    row_version=2,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_reject(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowRejectValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

            terminal_instance = _instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=uuid.uuid4(),
                current_state_id=state_id,
                status="completed",
                row_version=4,
                pending_task_id=task_id,
            )
            svc._get_for_action = AsyncMock(return_value=terminal_instance)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_cancel_instance(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowCancelInstanceValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

        awaiting = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=uuid.uuid4(),
            current_state_id=state_id,
            status="awaiting_approval",
            row_version=5,
            pending_transition_id=transition_id,
            pending_task_id=task_id,
        )
        svc._get_for_action = AsyncMock(return_value=awaiting)
        svc._transition_service.get = AsyncMock(
            return_value=_transition(
                transition_id=transition_id,
                tenant_id=tenant_id,
                workflow_version_id=awaiting.workflow_version_id,
                from_state_id=state_id,
                to_state_id=uuid.uuid4(),
                key="approval",
                requires_approval=True,
            )
        )
        svc._task_service.get = AsyncMock(
            return_value=_task(
                task_id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="open",
                row_version=2,
            )
        )
        svc._update_pending_task = AsyncMock(
            return_value=_task(
                task_id=None,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="completed",
                row_version=3,
            )
        )
        svc._require_open_decision_request = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                workflow_task_id=task_id,
                status="open",
                row_version=6,
            )
        )
        svc._decision_request_service.action_resolve = AsyncMock(
            return_value=({"DecisionRequestId": str(uuid.uuid4())}, 200)
        )
        svc._append_event = AsyncMock()
        svc._apply_transition = AsyncMock(return_value=("", 204))
        approve_result = await svc.action_approve(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowApproveValidation(row_version=5),
        )
        self.assertEqual(approve_result, ("", 204))
        svc._append_event.assert_not_awaited()

        rejecting = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=uuid.uuid4(),
            current_state_id=state_id,
            status="awaiting_approval",
            row_version=6,
            pending_task_id=task_id,
        )
        svc._get_for_action = AsyncMock(return_value=rejecting)
        svc._task_service.get = AsyncMock(
            return_value=_task(
                task_id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="open",
                row_version=2,
            )
        )
        svc._update_pending_task = AsyncMock(
            return_value=_task(
                task_id=None,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="rejected",
                row_version=3,
            )
        )
        svc._require_open_decision_request = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                workflow_task_id=task_id,
                status="open",
                row_version=4,
            )
        )
        svc._decision_request_service.action_cancel = AsyncMock(
            return_value=({"DecisionRequestId": str(uuid.uuid4())}, 200)
        )
        svc._update_instance_with_row_version = AsyncMock()
        svc._append_event = AsyncMock()
        reject_result = await svc.action_reject(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowRejectValidation(row_version=6, reason=" "),
        )
        self.assertEqual(reject_result, ("", 204))
        self.assertEqual(svc._append_event.await_count, 1)
        self.assertEqual(svc._append_event.await_args.kwargs["event_type"], "rejected")

        cancellable = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=uuid.uuid4(),
            current_state_id=state_id,
            status="active",
            row_version=7,
            pending_task_id=task_id,
        )
        now = datetime(2026, 2, 14, 19, 0, tzinfo=timezone.utc)
        svc._now_utc = Mock(return_value=now)
        svc._get_for_action = AsyncMock(return_value=cancellable)
        svc._task_service.get = AsyncMock(
            return_value=_task(
                task_id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="in_progress",
                row_version=3,
            )
        )
        svc._update_pending_task = AsyncMock(
            return_value=_task(
                task_id=task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="cancelled",
                row_version=4,
            )
        )
        svc._find_open_decision_request = AsyncMock(return_value=None)
        svc._update_instance_with_row_version = AsyncMock()
        svc._append_event = AsyncMock()
        cancel_result = await svc.action_cancel_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCancelInstanceValidation(row_version=7, reason="  "),
        )
        self.assertEqual(cancel_result, ("", 204))
        cancel_events = [
            call.kwargs["event_type"] for call in svc._append_event.await_args_list
        ]
        self.assertEqual(cancel_events, ["task_completed", "cancelled"])

    async def test_remaining_advance_and_cancel_branch_paths(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        version_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}
        now = datetime(2026, 2, 14, 19, 30, tzinfo=timezone.utc)

        resolve_svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        transition_without_key = _transition(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            to_state_id=uuid.uuid4(),
            key="fallback",
        )
        resolve_svc._transition_service.list = AsyncMock(
            return_value=[transition_without_key]
        )
        resolved = await resolve_svc._resolve_transition(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            transition_key=None,
            to_state_id=transition_without_key.to_state_id,
        )
        self.assertEqual(resolved.id, transition_without_key.id)
        resolved_where = resolve_svc._transition_service.list.await_args.kwargs[
            "filter_groups"
        ][0].where
        self.assertNotIn("key", resolved_where)
        self.assertEqual(
            resolved_where["to_state_id"],
            transition_without_key.to_state_id,
        )

        advance_svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        advance_svc._now_utc = Mock(return_value=now)
        active = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            current_state_id=state_id,
            status="active",
            row_version=8,
        )
        requires_approval = _transition(
            transition_id=uuid.uuid4(),
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            to_state_id=uuid.uuid4(),
            key="needs_review",
            requires_approval=True,
            auto_assign_queue="ops-auto",
        )
        advance_svc._get_for_action = AsyncMock(return_value=active)
        advance_svc._resolve_transition = AsyncMock(return_value=requires_approval)
        advance_svc._task_service.create = AsyncMock(
            return_value=_task(
                task_id=uuid.uuid4(),
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="open",
                row_version=1,
            )
        )
        advance_svc._decision_request_service.action_open = AsyncMock(
            return_value=({"DecisionRequestId": str(uuid.uuid4())}, 201)
        )
        advance_svc._update_instance_with_row_version = AsyncMock()
        advance_svc._append_event = AsyncMock()
        result = await advance_svc.action_advance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowAdvanceValidation(
                row_version=8,
                transition_key="needs_review",
                queue_name="  ops-l1  ",
            ),
        )
        self.assertEqual(result, ("", 204))
        create_payload = advance_svc._task_service.create.await_args.args[0]
        self.assertEqual(create_payload["queue_name"], "ops-l1")
        self.assertEqual(create_payload["assigned_by_user_id"], actor_id)

        cancel_without_pending = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        cancel_without_pending._now_utc = Mock(return_value=now)
        cancel_without_pending._get_for_action = AsyncMock(
            return_value=_instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                current_state_id=state_id,
                status="active",
                row_version=9,
                pending_task_id=None,
            )
        )
        cancel_without_pending._task_service.get = AsyncMock()
        cancel_without_pending._find_open_decision_request = AsyncMock(return_value=None)
        cancel_without_pending._update_instance_with_row_version = AsyncMock()
        cancel_without_pending._append_event = AsyncMock()
        cancel_result = await cancel_without_pending.action_cancel_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCancelInstanceValidation(row_version=9, reason="no-task"),
        )
        self.assertEqual(cancel_result, ("", 204))
        cancel_without_pending._task_service.get.assert_not_awaited()

        cancel_with_completed_task = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        pending_task_id = uuid.uuid4()
        cancel_with_completed_task._now_utc = Mock(return_value=now)
        cancel_with_completed_task._get_for_action = AsyncMock(
            return_value=_instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                current_state_id=state_id,
                status="active",
                row_version=10,
                pending_task_id=pending_task_id,
            )
        )
        cancel_with_completed_task._task_service.get = AsyncMock(
            return_value=_task(
                task_id=pending_task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="completed",
                row_version=1,
            )
        )
        cancel_with_completed_task._find_open_decision_request = AsyncMock(
            return_value=None
        )
        cancel_with_completed_task._update_pending_task = AsyncMock()
        cancel_with_completed_task._update_instance_with_row_version = AsyncMock()
        cancel_with_completed_task._append_event = AsyncMock()
        cancel_result = await cancel_with_completed_task.action_cancel_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCancelInstanceValidation(row_version=10, reason="done"),
        )
        self.assertEqual(cancel_result, ("", 204))
        cancel_with_completed_task._update_pending_task.assert_not_awaited()

        cancel_with_idless_update = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        cancel_with_idless_update._now_utc = Mock(return_value=now)
        cancel_with_idless_update._get_for_action = AsyncMock(
            return_value=_instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                current_state_id=state_id,
                status="active",
                row_version=11,
                pending_task_id=pending_task_id,
            )
        )
        cancel_with_idless_update._task_service.get = AsyncMock(
            return_value=_task(
                task_id=pending_task_id,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="open",
                row_version=2,
            )
        )
        cancel_with_idless_update._update_pending_task = AsyncMock(
            return_value=_task(
                task_id=None,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                status="cancelled",
                row_version=3,
            )
        )
        cancel_with_idless_update._find_open_decision_request = AsyncMock(
            return_value=None
        )
        cancel_with_idless_update._update_instance_with_row_version = AsyncMock()
        cancel_with_idless_update._append_event = AsyncMock()
        cancel_result = await cancel_with_idless_update.action_cancel_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCancelInstanceValidation(row_version=11, reason="cleanup"),
        )
        self.assertEqual(cancel_result, ("", 204))
        self.assertEqual(cancel_with_idless_update._append_event.await_count, 1)
        self.assertEqual(
            cancel_with_idless_update._append_event.await_args.kwargs["event_type"],
            "cancelled",
        )

    async def test_new_helper_methods_for_json_payload_hash_and_uuid(self) -> None:
        aware = datetime(2026, 2, 16, 15, 0, tzinfo=timezone.utc)
        naive = datetime(2026, 2, 16, 16, 0)

        self.assertIsNone(WorkflowInstanceService._to_aware_utc(None))
        self.assertEqual(
            WorkflowInstanceService._to_aware_utc(naive),
            datetime(2026, 2, 16, 16, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(WorkflowInstanceService._to_aware_utc(aware), aware)

        normalized = WorkflowInstanceService._json_safe(
            {"b": {3, 1}, "a": (uuid.uuid4(), naive)}
        )
        self.assertEqual(list(normalized.keys()), ["a", "b"])
        self.assertIsInstance(normalized["a"][0], str)
        self.assertEqual(normalized["a"][1], "2026-02-16T16:00:00+00:00")
        self.assertEqual(normalized["b"], [1, 3])
        self.assertEqual(
            WorkflowInstanceService._json_safe([aware]),
            ["2026-02-16T15:00:00+00:00"],
        )

        self.assertEqual(WorkflowInstanceService._response_parts(("", 204)), (204, ""))
        self.assertEqual(
            WorkflowInstanceService._response_parts({"ok": True}),
            (200, {"ok": True}),
        )

        self.assertEqual(
            WorkflowInstanceService._response_from_store(
                WorkflowActionDedupDE(response_code=204, response_json=None)
            ),
            ("", 204),
        )
        self.assertEqual(
            WorkflowInstanceService._response_from_store(
                WorkflowActionDedupDE(response_code=200, response_json={"x": 1})
            ),
            ({"x": 1}, 200),
        )

        hash_from_model = WorkflowInstanceService._payload_hash(
            data=WorkflowAdvanceValidation(row_version=5, transition_key="next"),
            exclude_fields={"row_version"},
        )
        hash_from_dict = WorkflowInstanceService._payload_hash(
            data={"transition_key": "next", "row_version": 5},
            exclude_fields={"row_version"},
        )
        self.assertEqual(hash_from_model, hash_from_dict)

        class _PlainObject:
            def __init__(self) -> None:
                self.transition_key = "next"
                self.row_version = 5

        class _ListModel:
            @staticmethod
            def model_dump(*args, **kwargs):  # noqa: ARG004
                return ["x", "y"]

        hash_from_object = WorkflowInstanceService._payload_hash(
            data=_PlainObject(),
            exclude_fields={"row_version"},
        )
        hash_from_list_model = WorkflowInstanceService._payload_hash(
            data=_ListModel(),
            exclude_fields={"ignored"},
        )
        self.assertIsInstance(hash_from_object, str)
        self.assertIsInstance(hash_from_list_model, str)

        left = uuid.uuid4()
        right = uuid.UUID(str(left))
        self.assertEqual(WorkflowInstanceService._uuid_text(left), str(left))
        self.assertTrue(WorkflowInstanceService._uuid_equal(left, right))
        self.assertFalse(WorkflowInstanceService._uuid_equal(left, uuid.uuid4()))

    async def test_next_event_seq_ordering_and_derive_state_helpers(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )

        svc._event_seq_cache[(tenant_id, instance_id)] = 7
        self.assertEqual(
            await svc._next_event_seq(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            ),
            8,
        )

        svc._event_seq_cache = {}
        svc._event_service.list = AsyncMock(return_value=[WorkflowEventDE(event_seq=4)])
        svc._event_service.count = AsyncMock(return_value=99)
        self.assertEqual(
            await svc._next_event_seq(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            ),
            5,
        )

        svc._event_seq_cache = {}
        svc._event_service.list = AsyncMock(return_value=[])
        svc._event_service.count = AsyncMock(return_value=3)
        self.assertEqual(
            await svc._next_event_seq(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            ),
            4,
        )

        svc._event_seq_cache = {}
        svc._event_service.list = AsyncMock(side_effect=Exception("boom"))
        self.assertEqual(
            await svc._next_event_seq(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            ),
            1,
        )

        event_a = WorkflowEventDE(
            id=uuid.uuid4(),
            event_seq=None,
            occurred_at=datetime(2026, 2, 16, 10, 0, tzinfo=timezone.utc),
        )
        event_b = WorkflowEventDE(
            id=uuid.uuid4(),
            event_seq=2,
            occurred_at=datetime(2026, 2, 16, 12, 0, tzinfo=timezone.utc),
        )
        event_c = WorkflowEventDE(
            id=uuid.uuid4(),
            event_seq=1,
            occurred_at=datetime(2026, 2, 16, 11, 0),
        )
        svc._event_service.list = AsyncMock(return_value=[event_a, event_b, event_c])
        ordered = await svc._ordered_events(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
        )
        self.assertEqual([e.id for e in ordered], [event_c.id, event_b.id, event_a.id])

        state_1 = uuid.uuid4()
        state_2 = uuid.uuid4()
        task_1 = uuid.uuid4()
        derived = WorkflowInstanceService._derive_state_from_events(
            events=[
                WorkflowEventDE(event_type="created", payload={"status": "draft"}),
                WorkflowEventDE(event_type="started", to_state_id=state_1),
                WorkflowEventDE(
                    event_type="approval_requested", workflow_task_id=task_1
                ),
                WorkflowEventDE(event_type="decision_opened"),
                WorkflowEventDE(
                    event_type="advanced",
                    to_state_id=state_2,
                    payload={"status": "active"},
                ),
                WorkflowEventDE(event_type="rejected"),
                WorkflowEventDE(event_type="cancelled"),
            ]
        )
        self.assertEqual(derived["status"], "cancelled")
        self.assertEqual(derived["current_state_id"], state_2)
        self.assertIsNone(derived["pending_task_id"])

        derived_without_created_status = (
            WorkflowInstanceService._derive_state_from_events(
                events=[WorkflowEventDE(event_type="created", payload={})]
            )
        )
        self.assertEqual(derived_without_created_status["status"], "draft")

    async def test_policy_binding_and_decision_lookup_helpers(self) -> None:
        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        task_id = uuid.uuid4()

        self.assertTrue(WorkflowInstanceService._boolish(True))
        self.assertFalse(WorkflowInstanceService._boolish(False))
        self.assertTrue(WorkflowInstanceService._boolish(" yes "))
        self.assertFalse(WorkflowInstanceService._boolish(" no "))
        self.assertFalse(WorkflowInstanceService._boolish("maybe"))
        self.assertTrue(WorkflowInstanceService._boolish(1))
        self.assertFalse(WorkflowInstanceService._boolish(0))
        self.assertTrue(WorkflowInstanceService._boolish(None, default=True))
        self.assertFalse(WorkflowInstanceService._boolish(object()))

        self.assertEqual(
            WorkflowInstanceService._binding_value({"PolicyCode": "A"}, "PolicyCode"),
            "A",
        )
        self.assertEqual(
            WorkflowInstanceService._binding_value(
                {"policycode": "B"},
                "PolicyCode",
            ),
            "B",
        )
        self.assertIsNone(
            WorkflowInstanceService._binding_value({"x": 1}, "PolicyCode")
        )

        self.assertEqual(
            WorkflowInstanceService._obligation_name({"Type": "Require_Approval"}),
            "require_approval",
        )
        self.assertIsNone(WorkflowInstanceService._obligation_name({"x": 1}))
        require_approval, require_reason_note = WorkflowInstanceService._obligation_flags(
            [
                "skip-non-mapping",
                {"Type": "require_approval"},
                {"Name": "log_reason", "Required": False},
                {"Name": "log_reason", "Required": True},
                {"Name": "ignored"},
            ]
        )
        self.assertTrue(require_approval)
        self.assertTrue(require_reason_note)

        decision_request = WorkflowDecisionRequestDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            workflow_task_id=task_id,
            status="open",
            row_version=2,
        )
        svc._decision_request_service.list = AsyncMock(return_value=[decision_request])
        found = await svc._find_open_decision_request(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            workflow_task_id=task_id,
        )
        self.assertEqual(found.id, decision_request.id)

        svc._decision_request_service.list = AsyncMock(return_value=[])
        self.assertIsNone(
            await svc._find_open_decision_request(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
            )
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc._decision_request_service.list = AsyncMock(
                side_effect=SQLAlchemyError("lookup failed")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._find_open_decision_request(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                )
            self.assertEqual(ex.exception.code, 500)

            svc._find_open_decision_request = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._require_open_decision_request(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    workflow_task_id=task_id,
                )
            self.assertEqual(ex.exception.code, 409)

        svc._find_open_decision_request = AsyncMock(return_value=decision_request)
        required = await svc._require_open_decision_request(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            workflow_task_id=task_id,
        )
        self.assertEqual(required.id, decision_request.id)

        svc._find_open_decision_request = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=None,
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                workflow_task_id=task_id,
                status="open",
                row_version=2,
            )
        )
        with self.assertRaises(HTTPException) as ex:
            await svc._require_open_decision_request(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                workflow_task_id=task_id,
            )
        self.assertEqual(ex.exception.code, 409)

        svc._find_open_decision_request = AsyncMock(
            return_value=WorkflowDecisionRequestDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                workflow_task_id=task_id,
                status="open",
                row_version=0,
            )
        )
        with self.assertRaises(HTTPException) as ex:
            await svc._require_open_decision_request(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                workflow_task_id=task_id,
            )
        self.assertEqual(ex.exception.code, 409)

    async def test_policy_binding_resolution_and_policy_guard_branches(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        version_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        policy_id = uuid.uuid4()
        transition = _transition(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            to_state_id=uuid.uuid4(),
            key="next",
        )
        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            invalid_binding_transition = _transition(
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                from_state_id=state_id,
                to_state_id=uuid.uuid4(),
                key="invalid",
            )
            invalid_binding_transition.attributes = {"PolicyDefinitionId": "not-a-uuid"}
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_transition_policy_binding(
                    tenant_id=tenant_id,
                    transition=invalid_binding_transition,
                    data=WorkflowAdvanceValidation(row_version=1, transition_key="invalid"),
                )
            self.assertEqual(ex.exception.code, 400)

            svc._policy_definition_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_transition_policy_binding(
                    tenant_id=tenant_id,
                    transition=transition,
                    data=WorkflowAdvanceValidation(
                        row_version=1,
                        transition_key="next",
                        policy_definition_id=policy_id,
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._policy_definition_service.get = AsyncMock(
                return_value=PolicyDefinitionDE(
                    id=policy_id,
                    tenant_id=tenant_id,
                    code="bound",
                    is_active=False,
                    row_version=1,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_transition_policy_binding(
                    tenant_id=tenant_id,
                    transition=transition,
                    data=WorkflowAdvanceValidation(
                        row_version=1,
                        transition_key="next",
                        policy_definition_id=policy_id,
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

            transition_with_code = _transition(
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                from_state_id=state_id,
                to_state_id=uuid.uuid4(),
                key="coded",
            )
            transition_with_code.attributes = {"PolicyCode": "code-a"}

            svc._policy_definition_service.list = AsyncMock(return_value=[])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_transition_policy_binding(
                    tenant_id=tenant_id,
                    transition=transition_with_code,
                    data=WorkflowAdvanceValidation(row_version=1, transition_key="coded"),
                )
            self.assertEqual(ex.exception.code, 409)

            single_candidate = PolicyDefinitionDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                code="code-a",
                is_active=True,
                row_version=1,
            )
            svc._policy_definition_service.list = AsyncMock(
                return_value=[single_candidate]
            )
            selected = await svc._resolve_transition_policy_binding(
                tenant_id=tenant_id,
                transition=transition_with_code,
                data=WorkflowAdvanceValidation(row_version=1, transition_key="coded"),
            )
            self.assertEqual(selected.id, single_candidate.id)

            svc._policy_definition_service.list = AsyncMock(
                return_value=[
                    PolicyDefinitionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        code="code-a",
                        is_active=True,
                        row_version=1,
                    ),
                    PolicyDefinitionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        code="code-a",
                        is_active=True,
                        row_version=2,
                    ),
                ]
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_transition_policy_binding(
                    tenant_id=tenant_id,
                    transition=transition_with_code,
                    data=WorkflowAdvanceValidation(row_version=1, transition_key="coded"),
                )
            self.assertEqual(ex.exception.code, 409)

        active_policy = PolicyDefinitionDE(
            id=policy_id,
            tenant_id=tenant_id,
            code="bound",
            is_active=True,
            row_version=3,
        )
        transition_with_uuid_binding = _transition(
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            from_state_id=state_id,
            to_state_id=uuid.uuid4(),
            key="uuid-bound",
        )
        transition_with_uuid_binding.attributes = {"PolicyDefinitionId": policy_id}
        svc._policy_definition_service.get = AsyncMock(return_value=active_policy)
        resolved_policy = await svc._resolve_transition_policy_binding(
            tenant_id=tenant_id,
            transition=transition_with_uuid_binding,
            data=WorkflowAdvanceValidation(row_version=1, transition_key="uuid-bound"),
        )
        self.assertEqual(resolved_policy.id, policy_id)

        current = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            workflow_version_id=version_id,
            current_state_id=state_id,
            status="active",
            row_version=5,
        )
        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc._resolve_transition_policy_binding = AsyncMock(
                return_value=PolicyDefinitionDE(
                    id=None,
                    tenant_id=tenant_id,
                    is_active=True,
                    row_version=1,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._evaluate_transition_policy(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    auth_user_id=actor_id,
                    current=current,
                    transition=transition,
                    data=WorkflowAdvanceValidation(row_version=5, transition_key="next"),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._resolve_transition_policy_binding = AsyncMock(
                return_value=PolicyDefinitionDE(
                    id=policy_id,
                    tenant_id=tenant_id,
                    is_active=True,
                    row_version=0,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._evaluate_transition_policy(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    auth_user_id=actor_id,
                    current=current,
                    transition=transition,
                    data=WorkflowAdvanceValidation(row_version=5, transition_key="next"),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._resolve_transition_policy_binding = AsyncMock(return_value=active_policy)
            svc._policy_definition_service.action_evaluate_policy = AsyncMock(
                return_value=({"Decision": "deny", "Obligations": []}, 200)
            )
            svc._maybe_replay_action_result = AsyncMock(return_value=None)
            svc._get_for_action = AsyncMock(return_value=current)
            svc._resolve_transition = AsyncMock(return_value=transition)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_advance(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where={"tenant_id": tenant_id, "id": instance_id},
                    auth_user_id=actor_id,
                    data=WorkflowAdvanceValidation(row_version=5, transition_key="next"),
                )
            self.assertEqual(ex.exception.code, 403)

            svc._policy_definition_service.action_evaluate_policy = AsyncMock(
                return_value=(
                    {
                        "Decision": "allow",
                        "Obligations": [{"Type": "log_reason", "Required": True}],
                    },
                    200,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_advance(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where={"tenant_id": tenant_id, "id": instance_id},
                    auth_user_id=actor_id,
                    data=WorkflowAdvanceValidation(row_version=5, transition_key="next"),
                )
            self.assertEqual(ex.exception.code, 400)

            approval_transition = _transition(
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                from_state_id=state_id,
                to_state_id=uuid.uuid4(),
                key="approval",
                requires_approval=True,
            )
            svc._resolve_transition = AsyncMock(return_value=approval_transition)
            svc._policy_definition_service.action_evaluate_policy = AsyncMock(
                return_value=({"Decision": "allow", "Obligations": []}, 200)
            )
            svc._task_service.create = AsyncMock(
                return_value=_task(
                    task_id=None,
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    status="open",
                    row_version=1,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_advance(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where={"tenant_id": tenant_id, "id": instance_id},
                    auth_user_id=actor_id,
                    data=WorkflowAdvanceValidation(row_version=5, transition_key="approval"),
                )
            self.assertEqual(ex.exception.code, 409)

        svc._resolve_transition_policy_binding = AsyncMock(return_value=active_policy)
        svc._policy_definition_service.action_evaluate_policy = AsyncMock(
            return_value=("not-a-mapping", 200)
        )
        self.assertIsNone(
            await svc._evaluate_transition_policy(
                tenant_id=tenant_id,
                entity_id=instance_id,
                auth_user_id=actor_id,
                current=current,
                transition=transition,
                data=WorkflowAdvanceValidation(
                    row_version=5,
                    transition_key="next",
                    payload={"x": 1},
                    note="ok",
                ),
            )
        )

    async def test_cancel_instance_fallback_cancels_linked_decision_request(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        version_id = uuid.uuid4()
        state_id = uuid.uuid4()
        task_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}
        now = datetime(2026, 2, 25, 12, 0, tzinfo=timezone.utc)

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        svc._now_utc = Mock(return_value=now)
        svc._get_for_action = AsyncMock(
            return_value=_instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                current_state_id=state_id,
                status="active",
                row_version=7,
                pending_task_id=task_id,
            )
        )
        svc._find_open_decision_request = AsyncMock(
            side_effect=[
                None,
                WorkflowDecisionRequestDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    workflow_task_id=task_id,
                    status="open",
                    row_version=3,
                ),
            ]
        )
        svc._decision_request_service.action_cancel = AsyncMock(
            return_value=({"DecisionRequestId": str(uuid.uuid4())}, 200)
        )
        svc._task_service.get = AsyncMock(return_value=None)
        svc._update_instance_with_row_version = AsyncMock()
        svc._append_event = AsyncMock()

        result = await svc.action_cancel_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCancelInstanceValidation(
                row_version=7,
                reason="  cancelled by operator ",
                note="  cleanup ",
            ),
        )
        self.assertEqual(result, ("", 204))
        self.assertEqual(svc._find_open_decision_request.await_count, 2)
        cancel_call = svc._decision_request_service.action_cancel.await_args.kwargs
        self.assertEqual(cancel_call["data"].reason, "cancelled by operator")
        self.assertEqual(cancel_call["data"].note, "cleanup")

    async def test_cancel_instance_uses_first_decision_lookup_when_present(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        version_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}
        now = datetime(2026, 2, 25, 13, 0, tzinfo=timezone.utc)

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        decision_request = WorkflowDecisionRequestDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            status="open",
            row_version=2,
        )
        svc._now_utc = Mock(return_value=now)
        svc._get_for_action = AsyncMock(
            return_value=_instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                current_state_id=state_id,
                status="active",
                row_version=3,
                pending_task_id=None,
            )
        )
        svc._find_open_decision_request = AsyncMock(return_value=decision_request)
        svc._decision_request_service.action_cancel = AsyncMock(
            return_value=({"DecisionRequestId": str(decision_request.id)}, 200)
        )
        svc._task_service.get = AsyncMock()
        svc._update_instance_with_row_version = AsyncMock()
        svc._append_event = AsyncMock()

        result = await svc.action_cancel_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCancelInstanceValidation(row_version=3, reason="cleanup"),
        )
        self.assertEqual(result, ("", 204))
        self.assertEqual(svc._find_open_decision_request.await_count, 1)
        svc._task_service.get.assert_not_awaited()

    async def test_maybe_replay_and_record_action_result_branches(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )

        no_key_data = WorkflowAdvanceValidation(row_version=1, transition_key="next")
        self.assertIsNone(
            await svc._maybe_replay_action_result(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                action_name="advance",
                data=no_key_data,
            )
        )

        keyed_data = WorkflowAdvanceValidation(
            row_version=1,
            transition_key="next",
            client_action_key="key-1",
        )
        request_hash = svc._payload_hash(
            data=keyed_data,
            exclude_fields={"row_version", "client_action_key"},
        )

        svc._action_dedup_service.get = AsyncMock(return_value=None)
        self.assertIsNone(
            await svc._maybe_replay_action_result(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                action_name="advance",
                data=keyed_data,
            )
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc._action_dedup_service.get = AsyncMock(
                return_value=WorkflowActionDedupDE(
                    request_hash="wrong",
                    response_code=200,
                    response_json={"ok": True},
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._maybe_replay_action_result(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    action_name="advance",
                    data=keyed_data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc._action_dedup_service.get = AsyncMock(
                return_value=WorkflowActionDedupDE(
                    request_hash=request_hash,
                    response_code=None,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._maybe_replay_action_result(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    action_name="advance",
                    data=keyed_data,
                )
            self.assertEqual(ex.exception.code, 409)

        svc._action_dedup_service.get = AsyncMock(
            return_value=WorkflowActionDedupDE(
                request_hash=request_hash,
                response_code=204,
                response_json=None,
            )
        )
        self.assertEqual(
            await svc._maybe_replay_action_result(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                action_name="advance",
                data=keyed_data,
            ),
            ("", 204),
        )

        svc._action_dedup_service.create = AsyncMock()
        await svc._record_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            action_name="advance",
            auth_user_id=actor_id,
            data=no_key_data,
            result=("", 204),
        )
        svc._action_dedup_service.create.assert_not_awaited()

        svc._action_dedup_service.get = AsyncMock(return_value=None)
        svc._action_dedup_service.create = AsyncMock(
            return_value=WorkflowActionDedupDE()
        )
        await svc._record_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            action_name="advance",
            auth_user_id=actor_id,
            data=keyed_data,
            result=("", 204),
        )
        create_payload = svc._action_dedup_service.create.await_args.args[0]
        self.assertEqual(create_payload["response_code"], 204)
        self.assertIsNone(create_payload["response_json"])

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc._action_dedup_service.get = AsyncMock(side_effect=[None, None])
            svc._action_dedup_service.create = AsyncMock(
                side_effect=IntegrityError("stmt", "params", Exception("dup"))
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._record_action_result(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    action_name="advance",
                    auth_user_id=actor_id,
                    data=keyed_data,
                    result={"ok": True},
                )
            self.assertEqual(ex.exception.code, 500)

            svc._action_dedup_service.get = AsyncMock(return_value=None)
            svc._action_dedup_service.create = AsyncMock(
                side_effect=SQLAlchemyError("boom")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._record_action_result(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    action_name="advance",
                    auth_user_id=actor_id,
                    data=keyed_data,
                    result={"ok": True},
                )
            self.assertEqual(ex.exception.code, 500)

            existing_after_integrity = WorkflowActionDedupDE(
                id=uuid.uuid4(),
                request_hash=request_hash,
                response_code=None,
                row_version=2,
            )
            svc._action_dedup_service.get = AsyncMock(
                side_effect=[None, existing_after_integrity]
            )
            svc._action_dedup_service.create = AsyncMock(
                side_effect=IntegrityError("stmt", "params", Exception("dup"))
            )
            svc._action_dedup_service.update_with_row_version = AsyncMock(
                return_value=existing_after_integrity
            )
            await svc._record_action_result(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                action_name="advance",
                auth_user_id=actor_id,
                data=keyed_data,
                result={"ok": True},
            )

            existing = WorkflowActionDedupDE(
                id=uuid.uuid4(),
                request_hash=request_hash,
                response_code=None,
                row_version=2,
            )
            svc._action_dedup_service.get = AsyncMock(return_value=existing)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._record_action_result(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    action_name="advance",
                    auth_user_id=actor_id,
                    data=WorkflowAdvanceValidation(
                        row_version=1,
                        transition_key="next",
                        client_action_key="key-1",
                        payload={"different": True},
                    ),
                    result={"ok": True},
                )
            self.assertEqual(ex.exception.code, 409)

            existing_done = WorkflowActionDedupDE(
                id=uuid.uuid4(),
                request_hash=request_hash,
                response_code=200,
                row_version=1,
            )
            svc._action_dedup_service.get = AsyncMock(return_value=existing_done)
            svc._action_dedup_service.update_with_row_version = AsyncMock()
            await svc._record_action_result(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                action_name="advance",
                auth_user_id=actor_id,
                data=keyed_data,
                result={"ok": True},
            )
            svc._action_dedup_service.update_with_row_version.assert_not_awaited()

            existing_pending = WorkflowActionDedupDE(
                id=uuid.uuid4(),
                request_hash=request_hash,
                response_code=None,
                row_version=3,
            )
            svc._action_dedup_service.get = AsyncMock(return_value=existing_pending)
            svc._action_dedup_service.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("ops_workflow_action_dedup")
            )
            await svc._record_action_result(
                tenant_id=tenant_id,
                workflow_instance_id=instance_id,
                action_name="advance",
                auth_user_id=actor_id,
                data=keyed_data,
                result={"ok": True},
            )

            svc._action_dedup_service.update_with_row_version = AsyncMock(
                side_effect=SQLAlchemyError("boom")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._record_action_result(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance_id,
                    action_name="advance",
                    auth_user_id=actor_id,
                    data=keyed_data,
                    result={"ok": True},
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_actions_return_dedup_replay_result_when_available(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}
        replay_result = ({"Replay": True}, 200)

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )
        svc._maybe_replay_action_result = AsyncMock(return_value=replay_result)
        svc._get_for_action = AsyncMock()

        start_result = await svc.action_start_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowStartInstanceValidation(
                row_version=1,
                client_action_key="key-start",
            ),
        )
        self.assertEqual(start_result, replay_result)

        advance_result = await svc.action_advance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowAdvanceValidation(
                row_version=1,
                transition_key="next",
                client_action_key="key-advance",
            ),
        )
        self.assertEqual(advance_result, replay_result)

        approve_result = await svc.action_approve(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowApproveValidation(
                row_version=1,
                client_action_key="key-approve",
            ),
        )
        self.assertEqual(approve_result, replay_result)

        reject_result = await svc.action_reject(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowRejectValidation(
                row_version=1,
                client_action_key="key-reject",
            ),
        )
        self.assertEqual(reject_result, replay_result)

        cancel_result = await svc.action_cancel_instance(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCancelInstanceValidation(
                row_version=1,
                client_action_key="key-cancel",
            ),
        )
        self.assertEqual(cancel_result, replay_result)
        svc._get_for_action.assert_not_awaited()

    async def test_action_replay_branches_and_repair(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}
        current_state_id = uuid.uuid4()
        pending_task_id = uuid.uuid4()

        svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance", rsg=Mock()
        )

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_replay(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowReplayValidation(repair=False),
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_replay(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowReplayValidation(repair=False),
                )
            self.assertEqual(ex.exception.code, 404)

        current = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            current_state_id=current_state_id,
            pending_task_id=pending_task_id,
            status="active",
            row_version=5,
        )
        replay_events = [
            WorkflowEventDE(
                event_type="started",
                to_state_id=uuid.uuid4(),
                payload={"status": "active"},
            ),
            WorkflowEventDE(
                event_type="approval_requested",
                workflow_task_id=uuid.uuid4(),
            ),
        ]
        svc.get = AsyncMock(return_value=current)
        svc._ordered_events = AsyncMock(return_value=replay_events)
        svc.update = AsyncMock()
        svc._append_event = AsyncMock()

        replay_result, status = await svc.action_replay(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowReplayValidation(repair=False),
        )
        self.assertEqual(status, 200)
        self.assertFalse(replay_result["RepairApplied"])
        self.assertIn("CurrentStateId", replay_result["Divergence"])
        self.assertIn("PendingTaskId", replay_result["Divergence"])
        svc.update.assert_not_awaited()

        replay_repair_result, status = await svc.action_replay(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowReplayValidation(repair=True),
        )
        self.assertEqual(status, 200)
        self.assertTrue(replay_repair_result["RepairApplied"])
        svc.update.assert_awaited()

        matching_svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        matching_state_id = uuid.uuid4()
        matching_task_id = uuid.uuid4()
        matching_current = _instance(
            instance_id=instance_id,
            tenant_id=tenant_id,
            current_state_id=matching_state_id,
            pending_task_id=matching_task_id,
            status="awaiting_approval",
            row_version=6,
        )
        matching_svc.get = AsyncMock(return_value=matching_current)
        matching_svc._ordered_events = AsyncMock(
            return_value=[
                WorkflowEventDE(
                    event_type="started",
                    to_state_id=matching_state_id,
                    payload={"status": "active"},
                ),
                WorkflowEventDE(
                    event_type="approval_requested",
                    workflow_task_id=matching_task_id,
                ),
            ]
        )
        matching_svc.update = AsyncMock()
        matching_svc._append_event = AsyncMock()
        matching_result, status = await matching_svc.action_replay(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowReplayValidation(repair=True),
        )
        self.assertEqual(status, 200)
        self.assertEqual(matching_result["Divergence"], {})
        self.assertFalse(matching_result["RepairApplied"])
        matching_svc.update.assert_not_awaited()

    async def test_action_compensate_paths_and_failures(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            missing_version_svc = WorkflowInstanceService(
                table="ops_workflow_workflow_instance",
                rsg=Mock(),
            )
            missing_version_svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=None,
                    row_version=3,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await missing_version_svc.action_compensate(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowCompensateValidation(
                        row_version=3,
                        transition_key="rollback",
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

            empty_transition_svc = WorkflowInstanceService(
                table="ops_workflow_workflow_instance",
                rsg=Mock(),
            )
            empty_transition_svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=uuid.uuid4(),
                    row_version=4,
                )
            )
            empty_transition_svc._transition_service.list = AsyncMock(return_value=[])
            with self.assertRaises(_AbortCalled) as ex:
                await empty_transition_svc.action_compensate(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowCompensateValidation(
                        row_version=4,
                        transition_key="rollback",
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

        transition_key_svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        version_id = uuid.uuid4()
        current_state_id = uuid.uuid4()
        transition_key_svc._get_for_action = AsyncMock(
            return_value=_instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                current_state_id=current_state_id,
                row_version=5,
            )
        )
        transition_key_svc._transition_service.list = AsyncMock(
            return_value=[
                _transition(
                    transition_id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    key="missing",
                    from_state_id=current_state_id,
                    to_state_id=uuid.uuid4(),
                    requires_approval=False,
                ),
                WorkflowTransitionDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    from_state_id=current_state_id,
                    to_state_id=uuid.uuid4(),
                    key="has_comp",
                    requires_approval=False,
                    compensation_json={"steps": ["undo"]},
                ),
            ]
        )
        transition_key_svc._append_event = AsyncMock()
        result, status = await transition_key_svc.action_compensate(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCompensateValidation(
                row_version=5,
                transition_key="rollback",
                note="plan-only",
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["ExecutionMode"], "plan_only")
        self.assertEqual(len(result["Planned"]), 1)
        self.assertEqual(len(result["Failed"]), 1)
        emitted_types = [
            c.kwargs["event_type"]
            for c in transition_key_svc._append_event.await_args_list
        ]
        self.assertEqual(
            emitted_types,
            [
                "compensation_requested",
                "compensation_failed",
                "compensation_planned",
            ],
        )

        pending_svc = WorkflowInstanceService(
            table="ops_workflow_workflow_instance",
            rsg=Mock(),
        )
        pending_transition_id = uuid.uuid4()
        pending_svc._get_for_action = AsyncMock(
            return_value=_instance(
                instance_id=instance_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                current_state_id=current_state_id,
                pending_transition_id=pending_transition_id,
                row_version=6,
            )
        )
        pending_svc._transition_service.get = AsyncMock(
            return_value=WorkflowTransitionDE(
                id=pending_transition_id,
                tenant_id=tenant_id,
                workflow_version_id=version_id,
                from_state_id=current_state_id,
                to_state_id=uuid.uuid4(),
                key="pending",
                compensation_json={"undo": True},
            )
        )
        pending_svc._append_event = AsyncMock()
        pending_result, status = await pending_svc.action_compensate(
            tenant_id=tenant_id,
            entity_id=instance_id,
            where=where,
            auth_user_id=actor_id,
            data=WorkflowCompensateValidation(row_version=6),
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(pending_result["Planned"]), 1)

        with patch.object(workflow_mod, "abort", side_effect=_abort_raiser):
            pending_missing_svc = WorkflowInstanceService(
                table="ops_workflow_workflow_instance",
                rsg=Mock(),
            )
            pending_missing_svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    current_state_id=current_state_id,
                    pending_transition_id=uuid.uuid4(),
                    row_version=7,
                )
            )
            pending_missing_svc._transition_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await pending_missing_svc.action_compensate(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowCompensateValidation(row_version=7),
                )
            self.assertEqual(ex.exception.code, 409)

            state_svc = WorkflowInstanceService(
                table="ops_workflow_workflow_instance",
                rsg=Mock(),
            )
            state_svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    current_state_id=current_state_id,
                    row_version=8,
                )
            )
            state_svc._transition_service.list = AsyncMock(return_value=[])
            with self.assertRaises(_AbortCalled) as ex:
                await state_svc.action_compensate(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowCompensateValidation(row_version=8),
                )
            self.assertEqual(ex.exception.code, 409)

            no_state_svc = WorkflowInstanceService(
                table="ops_workflow_workflow_instance",
                rsg=Mock(),
            )
            no_state_svc._get_for_action = AsyncMock(
                return_value=_instance(
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                    workflow_version_id=version_id,
                    current_state_id=None,
                    pending_transition_id=None,
                    row_version=9,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await no_state_svc.action_compensate(
                    tenant_id=tenant_id,
                    entity_id=instance_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=WorkflowCompensateValidation(row_version=9),
                )
            self.assertEqual(ex.exception.code, 409)
