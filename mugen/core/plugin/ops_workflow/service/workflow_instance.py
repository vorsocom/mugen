"""Provides a CRUD service for workflow instance lifecycle actions."""

__all__ = ["WorkflowInstanceService"]

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

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
)
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAdvanceValidation,
    WorkflowApproveValidation,
    WorkflowCancelInstanceValidation,
    WorkflowRejectValidation,
    WorkflowStartInstanceValidation,
)
from mugen.core.plugin.ops_workflow.contract.service.workflow_instance import (
    IWorkflowInstanceService,
)
from mugen.core.plugin.ops_workflow.domain import (
    WorkflowInstanceDE,
    WorkflowStateDE,
    WorkflowTaskDE,
    WorkflowTransitionDE,
)
from mugen.core.plugin.ops_workflow.service.workflow_event import WorkflowEventService
from mugen.core.plugin.ops_workflow.service.workflow_state import WorkflowStateService
from mugen.core.plugin.ops_workflow.service.workflow_task import WorkflowTaskService
from mugen.core.plugin.ops_workflow.service.workflow_transition import (
    WorkflowTransitionService,
)


class WorkflowInstanceService(
    IRelationalService[WorkflowInstanceDE],
    IWorkflowInstanceService,
):
    """A CRUD service for deterministic workflow instance transitions."""

    _STATE_TABLE = "ops_workflow_workflow_state"
    _TRANSITION_TABLE = "ops_workflow_workflow_transition"
    _TASK_TABLE = "ops_workflow_workflow_task"
    _EVENT_TABLE = "ops_workflow_workflow_event"

    _ALLOWED_ADVANCE_STATUS = {"active"}
    _TERMINAL_INSTANCE_STATUS = {"completed", "cancelled"}
    _ACTIVE_TASK_STATUS = {"open", "in_progress"}

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowInstanceDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._state_service = WorkflowStateService(table=self._STATE_TABLE, rsg=rsg)
        self._transition_service = WorkflowTransitionService(
            table=self._TRANSITION_TABLE,
            rsg=rsg,
        )
        self._task_service = WorkflowTaskService(table=self._TASK_TABLE, rsg=rsg)
        self._event_service = WorkflowEventService(table=self._EVENT_TABLE, rsg=rsg)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    async def create(self, values: Mapping[str, Any]) -> WorkflowInstanceDE:
        created = await super().create(values)

        if created.id is not None and created.tenant_id is not None:
            await self._append_event(
                tenant_id=created.tenant_id,
                workflow_instance_id=created.id,
                event_type="created",
                actor_user_id=created.last_actor_user_id,
                from_state_id=None,
                to_state_id=created.current_state_id,
                payload={"status": created.status},
            )

        return created

    async def _append_event(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
        event_type: str,
        actor_user_id: uuid.UUID | None,
        from_state_id: uuid.UUID | None,
        to_state_id: uuid.UUID | None,
        workflow_task_id: uuid.UUID | None = None,
        note: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        await self._event_service.create(
            {
                "tenant_id": tenant_id,
                "workflow_instance_id": workflow_instance_id,
                "workflow_task_id": workflow_task_id,
                "event_type": event_type,
                "from_state_id": from_state_id,
                "to_state_id": to_state_id,
                "actor_user_id": actor_user_id,
                "note": self._normalize_optional_text(note),
                "payload": dict(payload) if payload else None,
                "occurred_at": self._now_utc(),
            }
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> WorkflowInstanceDE:
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
            abort(404, "Workflow instance not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_instance_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> WorkflowInstanceDE:
        svc: ICrudServiceWithRowVersion[WorkflowInstanceDE] = self

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

    async def _resolve_initial_state(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_version_id: uuid.UUID,
        start_state_id: uuid.UUID | None,
    ) -> WorkflowStateDE:
        if start_state_id is not None:
            state = await self._state_service.get(
                {
                    "tenant_id": tenant_id,
                    "workflow_version_id": workflow_version_id,
                    "id": start_state_id,
                }
            )
            if state is None:
                abort(409, "StartStateId is not valid for this workflow version.")
            return state

        states = await self._state_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "workflow_version_id": workflow_version_id,
                        "is_initial": True,
                    }
                )
            ],
            limit=2,
        )
        if not states:
            abort(409, "No initial state is configured for this workflow version.")
        if len(states) > 1:
            abort(409, "Multiple initial states configured; transition is ambiguous.")
        return states[0]

    async def _resolve_transition(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_version_id: uuid.UUID,
        from_state_id: uuid.UUID,
        transition_key: str | None,
        to_state_id: uuid.UUID | None,
    ) -> WorkflowTransitionDE:
        where: dict[str, Any] = {
            "tenant_id": tenant_id,
            "workflow_version_id": workflow_version_id,
            "from_state_id": from_state_id,
            "is_active": True,
        }

        if transition_key is not None:
            clean_key = transition_key.strip()
            if not clean_key:
                abort(400, "TransitionKey cannot be empty.")
            where["key"] = clean_key

        if to_state_id is not None:
            where["to_state_id"] = to_state_id

        transitions = await self._transition_service.list(
            filter_groups=[FilterGroup(where=where)],
            limit=2,
        )
        if not transitions:
            abort(409, "No valid transition found from the current state.")
        if len(transitions) > 1:
            abort(409, "Transition is ambiguous; specify TransitionKey or ToStateId.")

        return transitions[0]

    async def _resolve_state(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_version_id: uuid.UUID,
        state_id: uuid.UUID,
    ) -> WorkflowStateDE:
        state = await self._state_service.get(
            {
                "tenant_id": tenant_id,
                "workflow_version_id": workflow_version_id,
                "id": state_id,
            }
        )
        if state is None:
            abort(409, "Transition target state could not be resolved.")
        return state

    async def _update_pending_task(
        self,
        *,
        task: WorkflowTaskDE,
        status: str,
        outcome: str,
        actor_user_id: uuid.UUID,
        now: datetime,
    ) -> WorkflowTaskDE:
        if task.id is None:
            abort(409, "Pending task identifier is missing.")

        where = {
            "tenant_id": task.tenant_id,
            "id": task.id,
            "workflow_instance_id": task.workflow_instance_id,
        }

        expected_row_version = int(task.row_version or 0)
        if expected_row_version <= 0:
            abort(409, "Pending task RowVersion is invalid.")

        try:
            updated = await self._task_service.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": status,
                    "completed_at": now,
                    "cancelled_at": now if status == "cancelled" else None,
                    "completed_by_user_id": actor_user_id,
                    "outcome": outcome,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict on pending task. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Pending task not found.")

        return updated

    async def _apply_transition(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        current: WorkflowInstanceDE,
        expected_row_version: int,
        transition: WorkflowTransitionDE,
        auth_user_id: uuid.UUID,
        event_type: str,
        note: str | None,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        if transition.to_state_id is None:
            abort(409, "Transition is missing ToStateId.")

        to_state = await self._resolve_state(
            tenant_id=tenant_id,
            workflow_version_id=current.workflow_version_id,
            state_id=transition.to_state_id,
        )

        now = self._now_utc()
        status = "completed" if bool(to_state.is_terminal) else "active"

        await self._update_instance_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": status,
                "current_state_id": to_state.id,
                "pending_transition_id": None,
                "pending_task_id": None,
                "completed_at": now if status == "completed" else None,
                "cancelled_at": None,
                "cancel_reason": None,
                "last_actor_user_id": auth_user_id,
            },
        )

        await self._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            event_type=event_type,
            actor_user_id=auth_user_id,
            from_state_id=current.current_state_id,
            to_state_id=to_state.id,
            note=note,
            payload=payload,
        )

        return "", 204

    async def action_start_instance(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowStartInstanceValidation,
    ) -> tuple[dict[str, Any], int]:
        """Start a draft workflow instance from its initial state."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "draft":
            abort(409, "Only draft instances can be started.")

        if current.workflow_version_id is None:
            abort(409, "Workflow instance is missing WorkflowVersionId.")

        initial_state = await self._resolve_initial_state(
            tenant_id=tenant_id,
            workflow_version_id=current.workflow_version_id,
            start_state_id=data.start_state_id,
        )

        now = self._now_utc()
        await self._update_instance_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "active",
                "current_state_id": initial_state.id,
                "started_at": current.started_at or now,
                "last_actor_user_id": auth_user_id,
            },
        )

        await self._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            event_type="started",
            actor_user_id=auth_user_id,
            from_state_id=None,
            to_state_id=initial_state.id,
            note=data.note,
            payload={"status": "active"},
        )

        return "", 204

    async def action_advance(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowAdvanceValidation,
    ) -> tuple[dict[str, Any], int]:
        """Advance an active instance through a deterministic transition."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status not in self._ALLOWED_ADVANCE_STATUS:
            abort(409, "Only active instances can be advanced.")

        if current.workflow_version_id is None or current.current_state_id is None:
            abort(409, "Instance is not in a state that can be advanced.")

        transition = await self._resolve_transition(
            tenant_id=tenant_id,
            workflow_version_id=current.workflow_version_id,
            from_state_id=current.current_state_id,
            transition_key=data.transition_key,
            to_state_id=data.to_state_id,
        )

        if transition.requires_approval:
            queue_name = self._normalize_optional_text(data.queue_name)
            if queue_name is None:
                queue_name = self._normalize_optional_text(transition.auto_assign_queue)

            assignee_user_id = data.assignee_user_id or transition.auto_assign_user_id
            is_assigned = assignee_user_id is not None or queue_name is not None

            now = self._now_utc()
            task = await self._task_service.create(
                {
                    "tenant_id": tenant_id,
                    "workflow_instance_id": entity_id,
                    "workflow_transition_id": transition.id,
                    "task_kind": "approval",
                    "status": "open",
                    "title": self._normalize_optional_text(data.task_title)
                    or f"Approval: {transition.key}",
                    "description": self._normalize_optional_text(
                        data.task_description
                    ),
                    "assignee_user_id": assignee_user_id,
                    "queue_name": queue_name,
                    "assigned_by_user_id": auth_user_id if is_assigned else None,
                    "assigned_at": now if is_assigned else None,
                    "payload": dict(data.payload) if data.payload else None,
                }
            )

            await self._update_instance_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "awaiting_approval",
                    "pending_transition_id": transition.id,
                    "pending_task_id": task.id,
                    "last_actor_user_id": auth_user_id,
                },
            )

            await self._append_event(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
                workflow_task_id=task.id,
                event_type="approval_requested",
                actor_user_id=auth_user_id,
                from_state_id=current.current_state_id,
                to_state_id=transition.to_state_id,
                note=data.note,
                payload={
                    "transition_key": transition.key,
                    "requires_approval": True,
                },
            )

            if task.id is not None and is_assigned:
                await self._append_event(
                    tenant_id=tenant_id,
                    workflow_instance_id=entity_id,
                    workflow_task_id=task.id,
                    event_type="task_assigned",
                    actor_user_id=auth_user_id,
                    from_state_id=current.current_state_id,
                    to_state_id=current.current_state_id,
                    payload={
                        "assignee_user_id": (
                            str(assignee_user_id) if assignee_user_id else None
                        ),
                        "queue_name": queue_name,
                        "handoff_count": 0,
                    },
                )

            return "", 204

        return await self._apply_transition(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where=where,
            current=current,
            expected_row_version=expected_row_version,
            transition=transition,
            auth_user_id=auth_user_id,
            event_type="advanced",
            note=data.note,
            payload={
                "transition_key": transition.key,
                "requires_approval": False,
            },
        )

    async def action_approve(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowApproveValidation,
    ) -> tuple[dict[str, Any], int]:
        """Approve a pending transition and advance to the target state."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "awaiting_approval":
            abort(409, "Instance is not awaiting approval.")
        if current.pending_transition_id is None or current.pending_task_id is None:
            abort(409, "Pending transition/task state is inconsistent.")

        transition = await self._transition_service.get(
            {
                "tenant_id": tenant_id,
                "id": current.pending_transition_id,
            }
        )
        if transition is None:
            abort(409, "Pending transition not found.")

        pending_task = await self._task_service.get(
            {
                "tenant_id": tenant_id,
                "id": current.pending_task_id,
                "workflow_instance_id": entity_id,
            }
        )
        if pending_task is None:
            abort(409, "Pending approval task not found.")
        if pending_task.status not in self._ACTIVE_TASK_STATUS:
            abort(409, "Pending approval task is not actionable.")

        now = self._now_utc()
        completed_task = await self._update_pending_task(
            task=pending_task,
            status="completed",
            outcome="approved",
            actor_user_id=auth_user_id,
            now=now,
        )

        if completed_task.id is not None:
            await self._append_event(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
                workflow_task_id=completed_task.id,
                event_type="task_completed",
                actor_user_id=auth_user_id,
                from_state_id=current.current_state_id,
                to_state_id=current.current_state_id,
                payload={"outcome": "approved"},
            )

        return await self._apply_transition(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where=where,
            current=current,
            expected_row_version=expected_row_version,
            transition=transition,
            auth_user_id=auth_user_id,
            event_type="approved",
            note=data.note,
            payload={
                "transition_key": transition.key,
                "task_id": str(completed_task.id),
            },
        )

    async def action_reject(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowRejectValidation,
    ) -> tuple[dict[str, Any], int]:
        """Reject a pending transition and clear approval state."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "awaiting_approval":
            abort(409, "Instance is not awaiting approval.")
        if current.pending_task_id is None:
            abort(409, "Pending approval task is missing.")

        pending_task = await self._task_service.get(
            {
                "tenant_id": tenant_id,
                "id": current.pending_task_id,
                "workflow_instance_id": entity_id,
            }
        )
        if pending_task is None:
            abort(409, "Pending approval task not found.")
        if pending_task.status not in self._ACTIVE_TASK_STATUS:
            abort(409, "Pending approval task is not actionable.")

        outcome = self._normalize_optional_text(data.reason) or "rejected"
        now = self._now_utc()
        completed_task = await self._update_pending_task(
            task=pending_task,
            status="rejected",
            outcome=outcome,
            actor_user_id=auth_user_id,
            now=now,
        )

        await self._update_instance_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "active",
                "pending_transition_id": None,
                "pending_task_id": None,
                "last_actor_user_id": auth_user_id,
            },
        )

        if completed_task.id is not None:
            await self._append_event(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
                workflow_task_id=completed_task.id,
                event_type="task_completed",
                actor_user_id=auth_user_id,
                from_state_id=current.current_state_id,
                to_state_id=current.current_state_id,
                payload={"outcome": outcome},
            )

        await self._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            event_type="rejected",
            actor_user_id=auth_user_id,
            from_state_id=current.current_state_id,
            to_state_id=current.current_state_id,
            note=data.note,
            payload={"reason": self._normalize_optional_text(data.reason)},
        )

        return "", 204

    async def action_cancel_instance(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowCancelInstanceValidation,
    ) -> tuple[dict[str, Any], int]:
        """Cancel an in-flight workflow instance."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status in self._TERMINAL_INSTANCE_STATUS:
            abort(409, "Completed/cancelled instances cannot be cancelled again.")

        now = self._now_utc()

        if current.pending_task_id is not None:
            pending_task = await self._task_service.get(
                {
                    "tenant_id": tenant_id,
                    "id": current.pending_task_id,
                    "workflow_instance_id": entity_id,
                }
            )
            if (
                pending_task is not None
                and pending_task.status in self._ACTIVE_TASK_STATUS
            ):
                cancelled_task = await self._update_pending_task(
                    task=pending_task,
                    status="cancelled",
                    outcome="cancelled",
                    actor_user_id=auth_user_id,
                    now=now,
                )
                if cancelled_task.id is not None:
                    await self._append_event(
                        tenant_id=tenant_id,
                        workflow_instance_id=entity_id,
                        workflow_task_id=cancelled_task.id,
                        event_type="task_completed",
                        actor_user_id=auth_user_id,
                        from_state_id=current.current_state_id,
                        to_state_id=current.current_state_id,
                        payload={"outcome": "cancelled"},
                    )

        await self._update_instance_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "cancelled",
                "cancelled_at": now,
                "cancel_reason": self._normalize_optional_text(data.reason),
                "pending_transition_id": None,
                "pending_task_id": None,
                "last_actor_user_id": auth_user_id,
            },
        )

        await self._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            event_type="cancelled",
            actor_user_id=auth_user_id,
            from_state_id=current.current_state_id,
            to_state_id=current.current_state_id,
            note=data.note,
            payload={"reason": self._normalize_optional_text(data.reason)},
        )

        return "", 204
