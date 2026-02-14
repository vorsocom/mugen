"""Branch coverage tests for ops_workflow WorkflowInstanceService."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAdvanceValidation,
    WorkflowApproveValidation,
    WorkflowCancelInstanceValidation,
    WorkflowRejectValidation,
    WorkflowStartInstanceValidation,
)
from mugen.core.plugin.ops_workflow.domain import (
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

    async def test_get_update_and_resolver_helper_branches(self) -> None:
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        version_id = uuid.uuid4()
        state_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": instance_id}

        svc = WorkflowInstanceService(table="ops_workflow_workflow_instance", rsg=Mock())
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

        svc = WorkflowInstanceService(table="ops_workflow_workflow_instance", rsg=Mock())
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

        svc = WorkflowInstanceService(table="ops_workflow_workflow_instance", rsg=Mock())
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
        start_changes = svc._update_instance_with_row_version.await_args.kwargs["changes"]
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
                    data=WorkflowAdvanceValidation(row_version=6, transition_key="next"),
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
                    data=WorkflowAdvanceValidation(row_version=6, transition_key="next"),
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

        svc = WorkflowInstanceService(table="ops_workflow_workflow_instance", rsg=Mock())

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

            svc._get_for_action = AsyncMock(return_value=_instance(status="active", row_version=4))
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
