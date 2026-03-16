"""Provides a CRUD service for workflow decision request actions."""

__all__ = ["WorkflowDecisionRequestService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
    WorkflowDecisionRequestCancelValidation,
    WorkflowDecisionRequestExpireOverdueValidation,
    WorkflowDecisionRequestOpenValidation,
    WorkflowDecisionRequestResolveValidation,
)
from mugen.core.plugin.ops_workflow.contract.service.workflow_decision_request import (
    IWorkflowDecisionRequestService,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowDecisionRequestDE
from mugen.core.plugin.ops_workflow.service.workflow_decision_outcome import (
    WorkflowDecisionOutcomeService,
)
from mugen.core.plugin.ops_workflow.service.workflow_event import WorkflowEventService


class WorkflowDecisionRequestService(
    IRelationalService[WorkflowDecisionRequestDE],
    IWorkflowDecisionRequestService,
):
    """A CRUD service for workflow-linked decision requests."""

    _OUTCOME_TABLE = "ops_workflow_decision_outcome"
    _EVENT_TABLE = "ops_workflow_workflow_event"
    _EVENT_SEQ_UNIQUE_CONSTRAINT = "ux_ops_wf_event_tenant_instance_event_seq"
    _OUTCOME_UNIQUE_CONSTRAINT = "ux_ops_wf_decision_outcome_tenant_request"
    _EVENT_APPEND_MAX_ATTEMPTS = 5

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowDecisionRequestDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._outcome_service = WorkflowDecisionOutcomeService(
            table=self._OUTCOME_TABLE,
            rsg=rsg,
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

    @classmethod
    def _integrity_constraint_name(cls, error: IntegrityError) -> str | None:
        orig = getattr(error, "orig", None)
        diag = getattr(orig, "diag", None)
        constraint_name = getattr(diag, "constraint_name", None)
        if isinstance(constraint_name, str) and constraint_name.strip():
            return constraint_name.strip()

        message = str(error)
        if cls._EVENT_SEQ_UNIQUE_CONSTRAINT in message:
            return cls._EVENT_SEQ_UNIQUE_CONSTRAINT
        if cls._OUTCOME_UNIQUE_CONSTRAINT in message:
            return cls._OUTCOME_UNIQUE_CONSTRAINT

        return None

    @classmethod
    def _is_event_seq_conflict(cls, error: IntegrityError) -> bool:
        return cls._integrity_constraint_name(error) == cls._EVENT_SEQ_UNIQUE_CONSTRAINT

    @classmethod
    def _is_outcome_unique_conflict(cls, error: IntegrityError) -> bool:
        return cls._integrity_constraint_name(error) == cls._OUTCOME_UNIQUE_CONSTRAINT

    @staticmethod
    def _to_aware_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    async def _next_event_seq(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
    ) -> int:
        cache_key = (tenant_id, workflow_instance_id)
        cached = self._event_seq_cache.get(cache_key)
        if cached is not None:
            next_seq = int(cached) + 1
            self._event_seq_cache[cache_key] = next_seq
            return next_seq

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
        return next_seq

    async def _append_event(
        self,
        *,
        decision_request: WorkflowDecisionRequestDE,
        event_type: str,
        actor_user_id: uuid.UUID,
        note: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if (
            decision_request.tenant_id is None
            or decision_request.workflow_instance_id is None
        ):
            return

        tenant_id = decision_request.tenant_id
        workflow_instance_id = decision_request.workflow_instance_id
        cache_key = (tenant_id, workflow_instance_id)
        for attempt in range(1, self._EVENT_APPEND_MAX_ATTEMPTS + 1):
            event_seq = await self._next_event_seq(
                tenant_id=tenant_id,
                workflow_instance_id=workflow_instance_id,
            )

            try:
                await self._event_service.create(
                    {
                        "tenant_id": tenant_id,
                        "workflow_instance_id": workflow_instance_id,
                        "workflow_task_id": decision_request.workflow_task_id,
                        "event_seq": event_seq,
                        "event_type": event_type,
                        "from_state_id": None,
                        "to_state_id": None,
                        "actor_user_id": actor_user_id,
                        "note": self._normalize_optional_text(note),
                        "payload": dict(payload) if payload else None,
                        "occurred_at": self._now_utc(),
                    }
                )
                return
            except IntegrityError as error:
                if not self._is_event_seq_conflict(error):
                    abort(500)
                self._event_seq_cache.pop(cache_key, None)
                if attempt >= self._EVENT_APPEND_MAX_ATTEMPTS:
                    abort(409, "Workflow event sequence conflict. Retry the action.")
            except SQLAlchemyError:
                abort(500)

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> WorkflowDecisionRequestDE:
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
            abort(404, "Decision request not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> WorkflowDecisionRequestDE:
        svc: ICrudServiceWithRowVersion[WorkflowDecisionRequestDE] = self

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

    async def action_open(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,
        data: WorkflowDecisionRequestOpenValidation,
    ) -> tuple[dict[str, Any], int]:
        """Open a workflow decision request."""
        try:
            created = await self.create(
                {
                    "tenant_id": tenant_id,
                    "trace_id": self._normalize_optional_text(data.trace_id),
                    "template_key": data.template_key.strip(),
                    "status": "open",
                    "requester_actor_json": (
                        dict(data.requester_actor_json)
                        if data.requester_actor_json
                        else None
                    ),
                    "assigned_to_json": (
                        dict(data.assigned_to_json) if data.assigned_to_json else None
                    ),
                    "options_json": (
                        dict(data.options_json) if data.options_json else None
                    ),
                    "context_json": (
                        dict(data.context_json) if data.context_json else None
                    ),
                    "workflow_instance_id": data.workflow_instance_id,
                    "workflow_task_id": data.workflow_task_id,
                    "due_at": self._to_aware_utc(data.due_at),
                    "attributes": dict(data.attributes) if data.attributes else None,
                }
            )
        except SQLAlchemyError:
            abort(500)

        if created.id is None:
            abort(500, "Decision request ID was not generated.")

        await self._append_event(
            decision_request=created,
            event_type="decision_opened",
            actor_user_id=auth_user_id,
            note=data.note,
            payload={
                "decision_request_id": str(created.id),
                "template_key": created.template_key,
                "trace_id": created.trace_id,
            },
        )

        return (
            {
                "DecisionRequestId": str(created.id),
                "Status": "open",
                "TraceId": created.trace_id,
            },
            201,
        )

    async def action_resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowDecisionRequestResolveValidation,
    ) -> tuple[dict[str, Any], int]:
        """Resolve an open workflow decision request and append an outcome row."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.id is None:
            abort(409, "Decision request identifier is missing.")
        if current.status != "open":
            abort(409, "Only open decision requests can be resolved.")

        now = self._now_utc()
        changes: dict[str, Any] = {
            "status": "resolved",
            "resolved_at": now,
        }
        if data.attributes is not None:
            changes["attributes"] = dict(data.attributes)

        updated = await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes=changes,
        )

        normalized_outcome = data.outcome.strip().lower()
        outcome_json = dict(data.outcome_json) if data.outcome_json else {}
        outcome_json.setdefault("outcome", normalized_outcome)
        if data.reason is not None:
            outcome_json.setdefault("reason", data.reason.strip())

        try:
            outcome = await self._outcome_service.create(
                {
                    "tenant_id": tenant_id,
                    "decision_request_id": entity_id,
                    "resolver_actor_json": (
                        dict(data.resolver_actor_json)
                        if data.resolver_actor_json
                        else {"UserId": str(auth_user_id)}
                    ),
                    "outcome_json": outcome_json,
                    "signature_json": (
                        dict(data.signature_json) if data.signature_json else None
                    ),
                }
            )
        except IntegrityError as error:
            if self._is_outcome_unique_conflict(error):
                abort(409, "Decision outcome already exists for this request.")
            abort(500)
        except SQLAlchemyError:
            abort(500)

        await self._append_event(
            decision_request=updated,
            event_type="decision_resolved",
            actor_user_id=auth_user_id,
            note=data.note,
            payload={
                "decision_request_id": str(entity_id),
                "decision_outcome_id": str(outcome.id) if outcome.id else None,
                "outcome": normalized_outcome,
                "reason": self._normalize_optional_text(data.reason),
            },
        )

        return (
            {
                "DecisionRequestId": str(entity_id),
                "DecisionOutcomeId": str(outcome.id) if outcome.id else None,
                "Status": "resolved",
                "Outcome": normalized_outcome,
            },
            200,
        )

    async def action_cancel(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowDecisionRequestCancelValidation,
    ) -> tuple[dict[str, Any], int]:
        """Cancel an open workflow decision request."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != "open":
            abort(409, "Only open decision requests can be cancelled.")

        updated = await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "cancelled",
                "resolved_at": self._now_utc(),
            },
        )

        await self._append_event(
            decision_request=updated,
            event_type="decision_cancelled",
            actor_user_id=auth_user_id,
            note=data.note,
            payload={
                "decision_request_id": str(entity_id),
                "reason": self._normalize_optional_text(data.reason),
            },
        )

        return (
            {
                "DecisionRequestId": str(entity_id),
                "Status": "cancelled",
            },
            200,
        )

    async def action_expire_overdue(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,
        data: WorkflowDecisionRequestExpireOverdueValidation,
    ) -> tuple[dict[str, Any], int]:
        """Expire open decision requests whose due date is at/before AsOfUtc."""
        as_of = self._to_aware_utc(data.as_of_utc) or self._now_utc()

        try:
            overdue = await self.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "status": "open",
                        },
                        scalar_filters=[
                            ScalarFilter(
                                field="due_at",
                                op=ScalarFilterOp.LTE,
                                value=as_of,
                            )
                        ],
                    )
                ],
                order_by=[OrderBy(field="due_at", descending=False)],
                limit=int(data.limit),
            )
        except SQLAlchemyError:
            abort(500)

        svc: ICrudServiceWithRowVersion[WorkflowDecisionRequestDE] = self
        expired_ids: list[str] = []
        for request in overdue:
            if request.id is None:
                continue
            expected_row_version = int(request.row_version or 0)
            if expected_row_version <= 0:
                continue

            try:
                updated = await svc.update_with_row_version(
                    where={"tenant_id": tenant_id, "id": request.id},
                    expected_row_version=expected_row_version,
                    changes={
                        "status": "expired",
                        "resolved_at": as_of,
                    },
                )
            except RowVersionConflict:
                continue
            except SQLAlchemyError:
                abort(500)

            if updated is None or updated.id is None:
                continue

            expired_ids.append(str(updated.id))
            await self._append_event(
                decision_request=updated,
                event_type="decision_expired",
                actor_user_id=auth_user_id,
                note=data.note,
                payload={
                    "decision_request_id": str(updated.id),
                    "as_of_utc": as_of.isoformat(),
                },
            )

        return (
            {
                "ExpiredCount": len(expired_ids),
                "ExpiredIds": expired_ids,
                "AsOfUtc": as_of.isoformat(),
            },
            200,
        )
