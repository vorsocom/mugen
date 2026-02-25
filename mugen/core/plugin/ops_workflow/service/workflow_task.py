"""Provides a CRUD service for workflow tasks and handoff actions."""

__all__ = ["WorkflowTaskService"]

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
    OrderBy,
    RowVersionConflict,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAssignTaskValidation,
    WorkflowCompleteTaskValidation,
)
from mugen.core.plugin.ops_workflow.contract.service.workflow_task import (
    IWorkflowTaskService,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowTaskDE
from mugen.core.plugin.ops_workflow.service.workflow_event import WorkflowEventService


class WorkflowTaskService(
    IRelationalService[WorkflowTaskDE],
    IWorkflowTaskService,
):
    """A CRUD service for workflow tasks and assignment transitions."""

    _EVENT_TABLE = "ops_workflow_workflow_event"
    _TERMINAL_STATUSES = {"completed", "rejected", "cancelled"}

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowTaskDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._event_service = WorkflowEventService(table=self._EVENT_TABLE, rsg=rsg)
        self._event_seq_cache: dict[tuple[uuid.UUID, uuid.UUID], int] = {}

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
    ) -> WorkflowTaskDE:
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
            abort(404, "Workflow task not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_task_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> WorkflowTaskDE:
        svc: ICrudServiceWithRowVersion[WorkflowTaskDE] = self

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

    async def _append_event(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
        workflow_task_id: uuid.UUID,
        event_type: str,
        actor_user_id: uuid.UUID,
        note: str | None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        cache_key = (tenant_id, workflow_instance_id)
        cached = self._event_seq_cache.get(cache_key)
        if cached is not None:
            next_seq = int(cached) + 1
        else:
            try:
                latest = await self._event_service.list(
                    filter_groups=[
                        FilterGroup(
                            where={
                                "tenant_id": tenant_id,
                                "workflow_instance_id": workflow_instance_id,
                            },
                            scalar_filters=[
                                ScalarFilter(
                                    field="event_seq",
                                    op=ScalarFilterOp.GT,
                                    value=0,
                                )
                            ],
                        )
                    ],
                    order_by=[OrderBy(field="event_seq", descending=True)],
                    limit=1,
                )
                if latest:
                    next_seq = int(latest[0].event_seq or 0) + 1
                else:
                    count = await self._event_service.count(
                        filter_groups=[
                            FilterGroup(
                                where={
                                    "tenant_id": tenant_id,
                                    "workflow_instance_id": workflow_instance_id,
                                }
                            )
                        ]
                    )
                    next_seq = int(count) + 1
            except Exception:  # noqa: BLE001
                next_seq = 1

        self._event_seq_cache[cache_key] = next_seq

        await self._event_service.create(
            {
                "tenant_id": tenant_id,
                "workflow_instance_id": workflow_instance_id,
                "workflow_task_id": workflow_task_id,
                "event_seq": next_seq,
                "event_type": event_type,
                "actor_user_id": actor_user_id,
                "note": self._normalize_optional_text(note),
                "payload": dict(payload) if payload else None,
                "occurred_at": self._now_utc(),
            }
        )

    async def action_assign_task(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowAssignTaskValidation,
    ) -> tuple[dict[str, Any], int]:
        """Assign or hand off a workflow task."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status in self._TERMINAL_STATUSES:
            abort(409, "Completed/rejected/cancelled tasks cannot be reassigned.")

        queue_name = self._normalize_optional_text(data.queue_name)
        old_queue_name = self._normalize_optional_text(current.queue_name)

        had_previous_target = (
            current.assignee_user_id is not None or old_queue_name is not None
        )
        assignment_changed = (
            current.assignee_user_id != data.assignee_user_id
            or old_queue_name != queue_name
        )

        handoff_count = int(current.handoff_count or 0)
        if had_previous_target and assignment_changed:
            handoff_count += 1

        now = self._now_utc()
        updated = await self._update_task_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "assignee_user_id": data.assignee_user_id,
                "queue_name": queue_name,
                "assigned_by_user_id": auth_user_id,
                "assigned_at": now,
                "handoff_count": handoff_count,
                "status": "in_progress" if current.status == "open" else current.status,
            },
        )

        if updated.id is not None and updated.workflow_instance_id is not None:
            await self._append_event(
                tenant_id=tenant_id,
                workflow_instance_id=updated.workflow_instance_id,
                workflow_task_id=updated.id,
                event_type="task_assigned",
                actor_user_id=auth_user_id,
                note=data.note,
                payload={
                    "assignee_user_id": (
                        str(data.assignee_user_id) if data.assignee_user_id else None
                    ),
                    "queue_name": queue_name,
                    "reason": self._normalize_optional_text(data.reason),
                    "handoff_count": handoff_count,
                },
            )

        return "", 204

    async def action_complete_task(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowCompleteTaskValidation,
    ) -> tuple[dict[str, Any], int]:
        """Complete a workflow task."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status in self._TERMINAL_STATUSES:
            abort(409, "Task is already terminal.")

        now = self._now_utc()
        outcome = self._normalize_optional_text(data.outcome) or "completed"

        updated = await self._update_task_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "completed",
                "completed_at": now,
                "cancelled_at": None,
                "completed_by_user_id": auth_user_id,
                "outcome": outcome,
            },
        )

        if updated.id is not None and updated.workflow_instance_id is not None:
            await self._append_event(
                tenant_id=tenant_id,
                workflow_instance_id=updated.workflow_instance_id,
                workflow_task_id=updated.id,
                event_type="task_completed",
                actor_user_id=auth_user_id,
                note=data.note,
                payload={"outcome": outcome},
            )

        return "", 204
