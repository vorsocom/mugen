"""Provides a CRUD service for workflow instance lifecycle actions."""

__all__ = ["WorkflowInstanceService"]

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from pydantic import ValidationError
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
from mugen.core.plugin.ops_governance.api.validation import (
    EvaluatePolicyActionValidation,
)
from mugen.core.plugin.ops_governance.domain import PolicyDefinitionDE
from mugen.core.plugin.ops_governance.service.policy_definition import (
    PolicyDefinitionService,
)
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAdvanceValidation,
    WorkflowApproveValidation,
    WorkflowCancelInstanceValidation,
    WorkflowCompensateValidation,
    WorkflowDecisionRequestCancelValidation,
    WorkflowDecisionRequestOpenValidation,
    WorkflowDecisionRequestResolveValidation,
    WorkflowRejectValidation,
    WorkflowReplayValidation,
    WorkflowStartInstanceValidation,
)
from mugen.core.plugin.ops_workflow.contract.service.workflow_instance import (
    IWorkflowInstanceService,
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
from mugen.core.plugin.ops_workflow.service.workflow_action_dedup import (
    WorkflowActionDedupService,
)
from mugen.core.plugin.ops_workflow.service.workflow_decision_request import (
    WorkflowDecisionRequestService,
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
    _ACTION_DEDUP_TABLE = "ops_workflow_action_dedup"
    _DECISION_REQUEST_TABLE = "ops_workflow_decision_request"
    _POLICY_DEFINITION_TABLE = "ops_governance_policy_definition"

    _ALLOWED_ADVANCE_STATUS = {"active"}
    _TERMINAL_INSTANCE_STATUS = {"completed", "cancelled"}
    _ACTIVE_TASK_STATUS = {"open", "in_progress"}
    _EVENT_SEQ_UNIQUE_CONSTRAINT = "ux_ops_wf_event_tenant_instance_event_seq"
    _EVENT_APPEND_MAX_ATTEMPTS = 5

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
        self._action_dedup_service = WorkflowActionDedupService(
            table=self._ACTION_DEDUP_TABLE,
            rsg=rsg,
        )
        self._decision_request_service = WorkflowDecisionRequestService(
            table=self._DECISION_REQUEST_TABLE,
            rsg=rsg,
        )
        self._policy_definition_service = PolicyDefinitionService(
            table=self._POLICY_DEFINITION_TABLE,
            rsg=rsg,
        )
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
    def _normalize_optional_note(cls, value: str | None) -> str | None:
        return cls._normalize_optional_text(value)

    @staticmethod
    def _safe_decision_open_validation(
        **values: Any,
    ) -> WorkflowDecisionRequestOpenValidation:
        try:
            return WorkflowDecisionRequestOpenValidation(**values)
        except ValidationError:
            abort(400, "Decision request open payload is invalid.")

    @staticmethod
    def _safe_decision_resolve_validation(
        **values: Any,
    ) -> WorkflowDecisionRequestResolveValidation:
        try:
            return WorkflowDecisionRequestResolveValidation(**values)
        except ValidationError:
            abort(400, "Decision request resolve payload is invalid.")

    @staticmethod
    def _safe_decision_cancel_validation(
        **values: Any,
    ) -> WorkflowDecisionRequestCancelValidation:
        try:
            return WorkflowDecisionRequestCancelValidation(**values)
        except ValidationError:
            abort(400, "Decision request cancel payload is invalid.")

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

        return None

    @classmethod
    def _is_event_seq_conflict(cls, error: IntegrityError) -> bool:
        return cls._integrity_constraint_name(error) == cls._EVENT_SEQ_UNIQUE_CONSTRAINT

    @staticmethod
    def _to_aware_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(k): cls._json_safe(v)
                for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, list):
            return [cls._json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [cls._json_safe(v) for v in value]
        if isinstance(value, set):
            normalized = [cls._json_safe(v) for v in value]
            return sorted(normalized, key=repr)
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        return value

    @classmethod
    def _response_parts(cls, result: Any) -> tuple[int, Any]:
        if (
            isinstance(result, tuple)
            and len(result) == 2
            and isinstance(result[1], int)
        ):
            return int(result[1]), result[0]
        return 200, result

    @classmethod
    def _response_from_store(
        cls, record: WorkflowActionDedupDE
    ) -> tuple[dict[str, Any], int]:
        code = int(record.response_code or 200)
        payload = record.response_json
        if code == 204 and payload is None:
            return "", 204
        return payload if payload is not None else "", code

    @classmethod
    def _payload_hash(
        cls,
        *,
        data: Any,
        exclude_fields: set[str] | None = None,
    ) -> str:
        payload: Any
        if hasattr(data, "model_dump") and callable(getattr(data, "model_dump")):
            payload = data.model_dump(mode="python", exclude_none=True)
        elif isinstance(data, Mapping):
            payload = dict(data)
        else:
            payload = dict(getattr(data, "__dict__", {}))

        for field in exclude_fields or set():
            if isinstance(payload, dict):
                payload.pop(field, None)

        encoded = json.dumps(
            cls._json_safe(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _uuid_text(value: uuid.UUID | None) -> str | None:
        return str(value) if value is not None else None

    @classmethod
    def _uuid_equal(cls, left: uuid.UUID | None, right: uuid.UUID | None) -> bool:
        return cls._uuid_text(left) == cls._uuid_text(right)

    @classmethod
    def _client_action_key(cls, data: Any) -> str | None:
        raw = getattr(data, "client_action_key", None)
        return cls._normalize_optional_text(raw)

    @classmethod
    def _boolish(cls, value: Any, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            clean = value.strip().lower()
            if clean in {"1", "true", "t", "yes", "y"}:
                return True
            if clean in {"0", "false", "f", "no", "n"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    @classmethod
    def _binding_value(cls, payload: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in payload:
                return payload[key]
            key_lower = key.lower()
            for candidate_key, candidate_value in payload.items():
                if str(candidate_key).lower() == key_lower:
                    return candidate_value
        return None

    @classmethod
    def _obligation_name(cls, obligation: Mapping[str, Any]) -> str | None:
        raw_name = cls._binding_value(
            obligation,
            "Name",
            "Type",
            "Action",
            "Obligation",
        )
        if raw_name is None:
            return None
        return cls._normalize_optional_text(str(raw_name).lower())

    @classmethod
    def _obligation_flags(cls, obligations: list[Any]) -> tuple[bool, bool]:
        require_approval = False
        require_reason_note = False

        for item in obligations:
            if not isinstance(item, Mapping):
                continue
            name = cls._obligation_name(item)
            if name == "require_approval":
                require_approval = True
                continue
            if name == "log_reason":
                required = cls._boolish(
                    cls._binding_value(item, "Required", "required"),
                    default=False,
                )
                if required:
                    require_reason_note = True

        return require_approval, require_reason_note

    async def _find_open_decision_request(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
        workflow_task_id: uuid.UUID | None = None,
    ) -> WorkflowDecisionRequestDE | None:
        where: dict[str, Any] = {
            "tenant_id": tenant_id,
            "workflow_instance_id": workflow_instance_id,
            "status": "open",
        }
        if workflow_task_id is not None:
            where["workflow_task_id"] = workflow_task_id

        try:
            matches = await self._decision_request_service.list(
                filter_groups=[FilterGroup(where=where)],
                order_by=[
                    OrderBy(field="created_at", descending=True),
                    OrderBy(field="id", descending=True),
                ],
                limit=1,
            )
        except SQLAlchemyError:
            abort(500)

        if not matches:
            return None
        return matches[0]

    async def _require_open_decision_request(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
        workflow_task_id: uuid.UUID,
    ) -> WorkflowDecisionRequestDE:
        decision_request = await self._find_open_decision_request(
            tenant_id=tenant_id,
            workflow_instance_id=workflow_instance_id,
            workflow_task_id=workflow_task_id,
        )
        if decision_request is None:
            abort(409, "Linked open decision request not found.")

        if decision_request.id is None:
            abort(409, "Decision request identifier is missing.")
        if int(decision_request.row_version or 0) <= 0:
            abort(409, "Decision request RowVersion is invalid.")
        return decision_request

    async def _get_or_create_legacy_decision_request(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
        workflow_task: WorkflowTaskDE,
        auth_user_id: uuid.UUID,
        trace_id: str | None = None,
        note: str | None = None,
    ) -> tuple[WorkflowDecisionRequestDE, bool]:
        if workflow_task.id is None:
            abort(409, "Pending approval task identifier is missing.")

        existing = await self._find_open_decision_request(
            tenant_id=tenant_id,
            workflow_instance_id=workflow_instance_id,
            workflow_task_id=workflow_task.id,
        )
        if existing is not None:
            if existing.id is None:
                abort(409, "Decision request identifier is missing.")
            if int(existing.row_version or 0) <= 0:
                abort(409, "Decision request RowVersion is invalid.")
            return existing, False

        bridge_open_data = self._safe_decision_open_validation(
            trace_id=self._normalize_optional_text(trace_id),
            template_key="workflow.approval.legacy_bridge",
            requester_actor_json={"UserId": str(auth_user_id)},
            assigned_to_json={
                "AssigneeUserId": self._uuid_text(workflow_task.assignee_user_id),
                "QueueName": self._normalize_optional_text(workflow_task.queue_name),
            },
            options_json={"LegacyBridge": True},
            context_json={
                "WorkflowInstanceId": str(workflow_instance_id),
                "WorkflowTaskId": str(workflow_task.id),
                "LegacyBridgeCreated": True,
            },
            workflow_instance_id=workflow_instance_id,
            workflow_task_id=workflow_task.id,
            note=self._normalize_optional_note(note),
        )
        await self._decision_request_service.action_open(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=auth_user_id,
            data=bridge_open_data,
        )

        bridged = await self._find_open_decision_request(
            tenant_id=tenant_id,
            workflow_instance_id=workflow_instance_id,
            workflow_task_id=workflow_task.id,
        )
        if bridged is None:
            abort(409, "Legacy bridge decision request was not created.")
        if bridged.id is None:
            abort(409, "Decision request identifier is missing.")
        if int(bridged.row_version or 0) <= 0:
            abort(409, "Decision request RowVersion is invalid.")
        return bridged, True

    @classmethod
    def _matches_advance_pending_snapshot(
        cls,
        *,
        instance: WorkflowInstanceDE,
        pending_transition_id: uuid.UUID | None,
        pending_task_id: uuid.UUID | None,
    ) -> bool:
        return (
            instance.status == "awaiting_approval"
            and cls._uuid_equal(instance.pending_transition_id, pending_transition_id)
            and cls._uuid_equal(instance.pending_task_id, pending_task_id)
        )

    async def _reconcile_advance_open_failure(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        current: WorkflowInstanceDE,
        task: WorkflowTaskDE,
        auth_user_id: uuid.UUID,
        pending_instance_row_version: int,
        pending_transition_id: uuid.UUID | None,
        pending_task_id: uuid.UUID | None,
        task_row_version: int,
    ) -> Literal["compensated", "reconciled"]:
        if task.id is not None:
            linked_request = await self._find_open_decision_request(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
                workflow_task_id=task.id,
            )
            if linked_request is not None:
                return "reconciled"

        latest_where = dict(where)
        latest_where["tenant_id"] = tenant_id
        latest_where["id"] = entity_id
        latest_where.pop("row_version", None)

        try:
            latest_instance = await self.get(latest_where)
        except SQLAlchemyError:
            abort(500)
        if latest_instance is None:
            abort(500, "Workflow instance compensation failed after decision open.")

        if not self._matches_advance_pending_snapshot(
            instance=latest_instance,
            pending_transition_id=pending_transition_id,
            pending_task_id=pending_task_id,
        ):
            return "reconciled"

        rollback_where = {
            "tenant_id": tenant_id,
            "id": entity_id,
            "status": "awaiting_approval",
            "pending_transition_id": pending_transition_id,
            "pending_task_id": pending_task_id,
        }
        expected_instance_row_version = int(pending_instance_row_version or 0)
        if expected_instance_row_version <= 0:
            expected_instance_row_version = int(latest_instance.row_version or 0)
        if expected_instance_row_version <= 0:
            abort(500, "Workflow instance compensation failed after decision open.")

        instance_svc: ICrudServiceWithRowVersion[WorkflowInstanceDE] = self
        compensated_instance: WorkflowInstanceDE | None = None
        for attempt in range(2):
            try:
                compensated_instance = await instance_svc.update_with_row_version(
                    where=rollback_where,
                    expected_row_version=expected_instance_row_version,
                    changes={
                        "status": "active",
                        "pending_transition_id": None,
                        "pending_task_id": None,
                        "last_actor_user_id": auth_user_id,
                    },
                )
            except RowVersionConflict:
                compensated_instance = None
            except SQLAlchemyError:
                abort(500)

            if compensated_instance is not None:
                break

            try:
                latest_instance = await self.get(latest_where)
            except SQLAlchemyError:
                abort(500)

            if latest_instance is not None and not self._matches_advance_pending_snapshot(
                instance=latest_instance,
                pending_transition_id=pending_transition_id,
                pending_task_id=pending_task_id,
            ):
                return "reconciled"

            if attempt == 0:
                expected_instance_row_version = (
                    int(latest_instance.row_version or 0)
                    if latest_instance is not None
                    else 0
                )
                if expected_instance_row_version <= 0:
                    abort(500, "Workflow instance compensation failed after decision open.")

        if compensated_instance is None:
            abort(500, "Workflow instance compensation failed after decision open.")

        if task.id is None:
            return "compensated"

        task_where = {
            "tenant_id": tenant_id,
            "id": task.id,
            "workflow_instance_id": entity_id,
        }
        try:
            latest_task = await self._task_service.get(task_where)
        except SQLAlchemyError:
            abort(500)
        if latest_task is None or latest_task.status not in self._ACTIVE_TASK_STATUS:
            return "compensated"

        now = self._now_utc()
        expected_task_row_version = int(task_row_version or 0)
        if expected_task_row_version <= 0:
            expected_task_row_version = int(latest_task.row_version or 0)
        if expected_task_row_version <= 0:
            abort(500, "Approval task compensation failed after decision open.")

        cancelled_task: WorkflowTaskDE | None = None
        for attempt in range(2):
            try:
                cancelled_task = await self._task_service.update_with_row_version(
                    where=task_where,
                    expected_row_version=expected_task_row_version,
                    changes={
                        "status": "cancelled",
                        "completed_at": now,
                        "cancelled_at": now,
                        "completed_by_user_id": auth_user_id,
                        "outcome": "decision_open_failed",
                    },
                )
            except RowVersionConflict:
                cancelled_task = None
            except SQLAlchemyError:
                abort(500)

            if cancelled_task is not None:
                break

            try:
                latest_task = await self._task_service.get(task_where)
            except SQLAlchemyError:
                abort(500)

            if latest_task is None or latest_task.status not in self._ACTIVE_TASK_STATUS:
                return "compensated"

            if attempt == 0:
                expected_task_row_version = int(latest_task.row_version or 0)
                if expected_task_row_version <= 0:
                    abort(500, "Approval task compensation failed after decision open.")

        if cancelled_task is None:
            abort(500, "Approval task compensation failed after decision open.")

        if cancelled_task.id is not None:
            await self._append_event(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
                workflow_task_id=cancelled_task.id,
                event_type="task_completed",
                actor_user_id=auth_user_id,
                from_state_id=current.current_state_id,
                to_state_id=current.current_state_id,
                payload={
                    "outcome": "decision_open_failed",
                    "reason": "decision_open_failed",
                },
            )

        return "compensated"

    async def _resolve_transition_policy_binding(
        self,
        *,
        tenant_id: uuid.UUID,
        transition: WorkflowTransitionDE,
        data: WorkflowAdvanceValidation,
    ) -> PolicyDefinitionDE | None:
        override_policy_definition_id = data.policy_definition_id
        override_policy_code = self._normalize_optional_text(data.policy_code)

        policy_definition_id: uuid.UUID | None = override_policy_definition_id
        policy_code: str | None = override_policy_code

        if policy_definition_id is None and policy_code is None:
            attrs = (
                transition.attributes
                if isinstance(transition.attributes, Mapping)
                else {}
            )

            raw_definition_id = self._binding_value(
                attrs,
                "PolicyDefinitionId",
                "policy_definition_id",
            )
            if isinstance(raw_definition_id, uuid.UUID):
                policy_definition_id = raw_definition_id
            elif isinstance(raw_definition_id, str):
                try:
                    policy_definition_id = uuid.UUID(raw_definition_id.strip())
                except ValueError:
                    abort(
                        400,
                        "Transition policy binding has invalid PolicyDefinitionId.",
                    )

            raw_policy_code = self._binding_value(attrs, "PolicyCode", "policy_code")
            if isinstance(raw_policy_code, str):
                policy_code = self._normalize_optional_text(raw_policy_code)

        if policy_definition_id is not None:
            policy = await self._policy_definition_service.get(
                {
                    "tenant_id": tenant_id,
                    "id": policy_definition_id,
                }
            )
            if policy is None:
                abort(409, "Bound policy definition was not found.")
            if not bool(policy.is_active):
                abort(409, "Bound policy definition is inactive.")
            return policy

        if policy_code is None:
            return None

        candidates = await self._policy_definition_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "code": policy_code,
                        "is_active": True,
                    }
                )
            ],
            limit=2,
        )
        if not candidates:
            abort(409, "Bound policy code did not resolve to an active policy.")
        if len(candidates) > 1:
            abort(409, "PolicyCode binding is ambiguous across active versions.")
        return candidates[0]

    async def _evaluate_transition_policy(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        current: WorkflowInstanceDE,
        transition: WorkflowTransitionDE,
        data: WorkflowAdvanceValidation,
    ) -> dict[str, Any] | None:
        policy = await self._resolve_transition_policy_binding(
            tenant_id=tenant_id,
            transition=transition,
            data=data,
        )
        if policy is None:
            return None
        if policy.id is None:
            abort(409, "Bound policy definition ID is missing.")
        policy_row_version = int(policy.row_version or 0)
        if policy_row_version <= 0:
            abort(409, "Bound policy definition RowVersion is invalid.")

        payload_json = dict(data.payload) if data.payload else {}
        input_json = {
            "WorkflowInstance": {
                "Id": str(entity_id),
                "WorkflowDefinitionId": self._uuid_text(current.workflow_definition_id),
                "WorkflowVersionId": self._uuid_text(current.workflow_version_id),
                "CurrentStateId": self._uuid_text(current.current_state_id),
                "SubjectNamespace": current.subject_namespace,
                "SubjectId": self._uuid_text(current.subject_id),
                "SubjectRef": current.subject_ref,
                "Status": current.status,
            },
            "Transition": {
                "Id": self._uuid_text(transition.id),
                "Key": transition.key,
                "FromStateId": self._uuid_text(transition.from_state_id),
                "ToStateId": self._uuid_text(transition.to_state_id),
                "RequiresApproval": bool(transition.requires_approval),
                "Attributes": dict(transition.attributes)
                if transition.attributes
                else None,
            },
            "ActionPayload": payload_json,
            "Note": self._normalize_optional_text(data.note),
        }

        evaluate_result, _status = (
            await self._policy_definition_service.action_evaluate_policy(
                tenant_id=tenant_id,
                entity_id=policy.id,
                where={"tenant_id": tenant_id, "id": policy.id},
                auth_user_id=auth_user_id,
                data=EvaluatePolicyActionValidation(
                    row_version=policy_row_version,
                    trace_id=self._client_action_key(data),
                    subject_namespace=current.subject_namespace
                    or "ops.workflow.instance",
                    subject_id=current.subject_id,
                    subject_ref=self._normalize_optional_text(current.subject_ref)
                    or str(entity_id),
                    input_json=input_json,
                    actor_json={"UserId": str(auth_user_id)},
                    request_context={
                        "WorkflowInstanceId": str(entity_id),
                        "WorkflowTransitionId": self._uuid_text(transition.id),
                    },
                ),
            )
        )

        return dict(evaluate_result) if isinstance(evaluate_result, Mapping) else None

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
                        "workflow_task_id": workflow_task_id,
                        "event_seq": event_seq,
                        "event_type": event_type,
                        "from_state_id": from_state_id,
                        "to_state_id": to_state_id,
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
                    abort(
                        409,
                        "Workflow event sequence conflict. Retry the action.",
                    )
            except SQLAlchemyError:
                abort(500)

    async def _maybe_replay_action_result(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
        action_name: str,
        data: Any,
    ) -> tuple[dict[str, Any], int] | None:
        client_action_key = self._client_action_key(data)
        if client_action_key is None:
            return None

        expected_hash = self._payload_hash(
            data=data,
            exclude_fields={"row_version", "client_action_key"},
        )

        existing = await self._action_dedup_service.get(
            {
                "tenant_id": tenant_id,
                "workflow_instance_id": workflow_instance_id,
                "action_name": action_name,
                "client_action_key": client_action_key,
            }
        )
        if existing is None:
            return None

        stored_hash = self._normalize_optional_text(existing.request_hash)
        if stored_hash != expected_hash:
            abort(409, "ClientActionKey payload hash mismatch.")

        if existing.response_code is None:
            abort(409, "ClientActionKey is in progress. Retry shortly.")

        return self._response_from_store(existing)

    async def _record_action_result(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
        action_name: str,
        auth_user_id: uuid.UUID,
        data: Any,
        result: tuple[dict[str, Any], int] | tuple[str, int] | Any,
    ) -> None:
        client_action_key = self._client_action_key(data)
        if client_action_key is None:
            return

        request_hash = self._payload_hash(
            data=data,
            exclude_fields={"row_version", "client_action_key"},
        )
        response_code, response_payload = self._response_parts(result)
        payload_to_store = (
            None
            if response_code == 204 and response_payload in (None, "")
            else self._json_safe(response_payload)
        )

        where = {
            "tenant_id": tenant_id,
            "workflow_instance_id": workflow_instance_id,
            "action_name": action_name,
            "client_action_key": client_action_key,
        }

        existing = await self._action_dedup_service.get(where)
        if existing is None:
            try:
                await self._action_dedup_service.create(
                    {
                        "tenant_id": tenant_id,
                        "workflow_instance_id": workflow_instance_id,
                        "action_name": action_name,
                        "client_action_key": client_action_key,
                        "request_hash": request_hash,
                        "response_code": response_code,
                        "response_json": payload_to_store,
                        "completed_at": self._now_utc(),
                        "last_actor_user_id": auth_user_id,
                    }
                )
                return
            except IntegrityError:
                existing = await self._action_dedup_service.get(where)
                if existing is None:
                    abort(500)
            except SQLAlchemyError:
                abort(500)

        stored_hash = self._normalize_optional_text(existing.request_hash)
        if stored_hash != request_hash:
            abort(409, "ClientActionKey payload hash mismatch.")

        if existing.response_code is not None:
            return

        try:
            await self._action_dedup_service.update_with_row_version(
                where={"id": existing.id},
                expected_row_version=int(existing.row_version or 1),
                changes={
                    "response_code": response_code,
                    "response_json": payload_to_store,
                    "completed_at": self._now_utc(),
                    "last_actor_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            return
        except SQLAlchemyError:
            abort(500)

    async def _ordered_events(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
    ) -> list[WorkflowEventDE]:
        events = list(
            await self._event_service.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "workflow_instance_id": workflow_instance_id,
                        }
                    )
                ],
                order_by=[
                    OrderBy(field="event_seq", descending=False),
                    OrderBy(field="occurred_at", descending=False),
                    OrderBy(field="id", descending=False),
                ],
            )
        )

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

        def _sort_key(event: WorkflowEventDE) -> tuple[int, int, datetime, str]:
            if event.event_seq is not None:
                return (
                    0,
                    int(event.event_seq),
                    self._to_aware_utc(event.occurred_at) or epoch,
                    str(event.id),
                )
            return (
                1,
                0,
                self._to_aware_utc(event.occurred_at) or epoch,
                str(event.id),
            )

        events.sort(key=_sort_key)
        return events

    @classmethod
    def _derive_state_from_events(
        cls,
        *,
        events: list[WorkflowEventDE],
    ) -> dict[str, Any]:
        status = "draft"
        current_state_id: uuid.UUID | None = None
        pending_task_id: uuid.UUID | None = None

        for event in events:
            event_type = (event.event_type or "").strip().lower()
            payload = event.payload or {}

            if event_type == "created":
                created_status = cls._normalize_optional_text(payload.get("status"))
                if created_status is not None:
                    status = created_status

            if event_type == "started":
                status = cls._normalize_optional_text(payload.get("status")) or "active"
                current_state_id = event.to_state_id or current_state_id
                pending_task_id = None
                continue

            if event_type == "approval_requested":
                status = "awaiting_approval"
                pending_task_id = event.workflow_task_id
                continue

            if event_type in {
                "decision_opened",
                "decision_resolved",
                "decision_expired",
                "decision_cancelled",
            }:
                continue

            if event_type in {"advanced", "approved"}:
                status = cls._normalize_optional_text(payload.get("status")) or "active"
                current_state_id = event.to_state_id or current_state_id
                pending_task_id = None
                continue

            if event_type == "rejected":
                status = "active"
                pending_task_id = None
                continue

            if event_type == "cancelled":
                status = "cancelled"
                pending_task_id = None
                continue

        return {
            "status": status,
            "current_state_id": current_state_id,
            "pending_task_id": pending_task_id,
        }

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

        event_payload: dict[str, Any] = dict(payload) if payload else {}
        event_payload["status"] = status

        await self._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            event_type=event_type,
            actor_user_id=auth_user_id,
            from_state_id=current.current_state_id,
            to_state_id=to_state.id,
            note=note,
            payload=event_payload,
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
        replay_result = await self._maybe_replay_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="start_instance",
            data=data,
        )
        if replay_result is not None:
            return replay_result

        expected_row_version = int(data.row_version)
        normalized_note = self._normalize_optional_note(data.note)
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

        result: tuple[dict[str, Any], int] = ("", 204)
        await self._record_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="start_instance",
            auth_user_id=auth_user_id,
            data=data,
            result=result,
        )
        return result

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
        replay_result = await self._maybe_replay_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="advance",
            data=data,
        )
        if replay_result is not None:
            return replay_result

        expected_row_version = int(data.row_version)
        normalized_note = self._normalize_optional_note(data.note)
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

        policy_summary = await self._evaluate_transition_policy(
            tenant_id=tenant_id,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            current=current,
            transition=transition,
            data=data,
        )
        obligations = (
            list(policy_summary.get("Obligations"))
            if isinstance(policy_summary, Mapping)
            and isinstance(policy_summary.get("Obligations"), list)
            else []
        )
        decision = (
            self._normalize_optional_text(str(policy_summary.get("Decision")))
            if isinstance(policy_summary, Mapping)
            and policy_summary.get("Decision") is not None
            else None
        )
        if decision == "deny":
            abort(403, "Policy decision denied the transition.")

        require_approval_from_policy, require_reason_note = self._obligation_flags(
            obligations
        )
        if require_reason_note and normalized_note is None:
            abort(400, "This transition requires a non-empty Note.")

        requires_approval = (
            bool(transition.requires_approval) or require_approval_from_policy
        )

        result: tuple[dict[str, Any], int]
        if requires_approval:
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
                    "description": self._normalize_optional_text(data.task_description),
                    "assignee_user_id": assignee_user_id,
                    "queue_name": queue_name,
                    "assigned_by_user_id": auth_user_id if is_assigned else None,
                    "assigned_at": now if is_assigned else None,
                    "payload": {
                        "ActionPayload": dict(data.payload) if data.payload else None,
                        "PolicySummary": policy_summary,
                        "PolicyObligations": obligations,
                    },
                }
            )

            if task.id is None:
                abort(409, "Approval task identifier is missing.")

            open_data = self._safe_decision_open_validation(
                trace_id=(
                    str(policy_summary.get("TraceId"))
                    if isinstance(policy_summary, Mapping)
                    and policy_summary.get("TraceId") is not None
                    else self._client_action_key(data)
                ),
                template_key="workflow.approval",
                requester_actor_json={"UserId": str(auth_user_id)},
                assigned_to_json={
                    "AssigneeUserId": (
                        str(assignee_user_id) if assignee_user_id else None
                    ),
                    "QueueName": queue_name,
                },
                options_json={
                    "TransitionKey": transition.key,
                },
                context_json={
                    "WorkflowInstanceId": str(entity_id),
                    "WorkflowTaskId": str(task.id),
                    "WorkflowTransitionId": self._uuid_text(transition.id),
                    "PolicySummary": policy_summary,
                },
                workflow_instance_id=entity_id,
                workflow_task_id=task.id,
                note=normalized_note,
            )

            pending_instance = await self._update_instance_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "awaiting_approval",
                    "pending_transition_id": transition.id,
                    "pending_task_id": task.id,
                    "last_actor_user_id": auth_user_id,
                },
            )

            try:
                open_result, _open_status = (
                    await self._decision_request_service.action_open(
                        tenant_id=tenant_id,
                        where={"tenant_id": tenant_id},
                        auth_user_id=auth_user_id,
                        data=open_data,
                    )
                )
            except Exception:
                reconcile_result = await self._reconcile_advance_open_failure(
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    where=where,
                    current=current,
                    task=task,
                    auth_user_id=auth_user_id,
                    pending_instance_row_version=int(pending_instance.row_version or 0),
                    pending_transition_id=pending_instance.pending_transition_id,
                    pending_task_id=pending_instance.pending_task_id,
                    task_row_version=int(task.row_version or 0),
                )
                if reconcile_result == "reconciled":
                    result = ("", 204)
                else:
                    raise
            else:
                decision_request_id = (
                    str(open_result.get("DecisionRequestId"))
                    if isinstance(open_result, Mapping)
                    and open_result.get("DecisionRequestId") is not None
                    else None
                )

                await self._append_event(
                    tenant_id=tenant_id,
                    workflow_instance_id=entity_id,
                    workflow_task_id=task.id,
                    event_type="approval_requested",
                    actor_user_id=auth_user_id,
                    from_state_id=current.current_state_id,
                    to_state_id=transition.to_state_id,
                    note=normalized_note,
                    payload={
                        "transition_key": transition.key,
                        "requires_approval": True,
                        "decision_request_id": decision_request_id,
                        "policy_summary": policy_summary,
                        "obligations": obligations,
                        "status": "awaiting_approval",
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

                result = ("", 204)
        else:
            result = await self._apply_transition(
                tenant_id=tenant_id,
                entity_id=entity_id,
                where=where,
                current=current,
                expected_row_version=expected_row_version,
                transition=transition,
                auth_user_id=auth_user_id,
                event_type="advanced",
                note=normalized_note,
                payload={
                    "transition_key": transition.key,
                    "requires_approval": False,
                    "policy_summary": policy_summary,
                    "obligations": obligations,
                },
            )

        await self._record_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="advance",
            auth_user_id=auth_user_id,
            data=data,
            result=result,
        )
        return result

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
        replay_result = await self._maybe_replay_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="approve",
            data=data,
        )
        if replay_result is not None:
            return replay_result

        expected_row_version = int(data.row_version)
        approve_note = self._normalize_optional_note(data.note)
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

        decision_request, legacy_bridge_created = (
            await self._get_or_create_legacy_decision_request(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
                workflow_task=pending_task,
                auth_user_id=auth_user_id,
                trace_id=self._client_action_key(data),
                note=approve_note,
            )
        )
        resolve_data = self._safe_decision_resolve_validation(
            row_version=int(decision_request.row_version or 0),
            outcome="approved",
            outcome_json={
                "transition_key": transition.key,
                "workflow_instance_id": str(entity_id),
                "workflow_task_id": str(current.pending_task_id),
            },
            note=approve_note,
        )
        await self._decision_request_service.action_resolve(
            tenant_id=tenant_id,
            entity_id=decision_request.id,
            where={
                "tenant_id": tenant_id,
                "id": decision_request.id,
            },
            auth_user_id=auth_user_id,
            data=resolve_data,
        )

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

        result = await self._apply_transition(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where=where,
            current=current,
            expected_row_version=expected_row_version,
            transition=transition,
            auth_user_id=auth_user_id,
            event_type="approved",
            note=approve_note,
            payload={
                "transition_key": transition.key,
                "task_id": str(completed_task.id),
                "decision_request_id": str(decision_request.id),
                "legacy_bridge_created": legacy_bridge_created,
            },
        )

        await self._record_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="approve",
            auth_user_id=auth_user_id,
            data=data,
            result=result,
        )
        return result

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
        replay_result = await self._maybe_replay_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="reject",
            data=data,
        )
        if replay_result is not None:
            return replay_result

        expected_row_version = int(data.row_version)
        reject_reason = self._normalize_optional_text(data.reason)
        reject_note = self._normalize_optional_note(data.note)
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

        decision_request, legacy_bridge_created = (
            await self._get_or_create_legacy_decision_request(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
                workflow_task=pending_task,
                auth_user_id=auth_user_id,
                trace_id=self._client_action_key(data),
                note=reject_note,
            )
        )
        cancel_data = self._safe_decision_cancel_validation(
            row_version=int(decision_request.row_version or 0),
            reason=reject_reason,
            note=reject_note,
        )
        await self._decision_request_service.action_cancel(
            tenant_id=tenant_id,
            entity_id=decision_request.id,
            where={
                "tenant_id": tenant_id,
                "id": decision_request.id,
            },
            auth_user_id=auth_user_id,
            data=cancel_data,
        )

        outcome = reject_reason or "rejected"
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
            note=reject_note,
            payload={
                "reason": reject_reason,
                "decision_request_id": str(decision_request.id),
                "legacy_bridge_created": legacy_bridge_created,
                "status": "active",
            },
        )

        result: tuple[dict[str, Any], int] = ("", 204)
        await self._record_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="reject",
            auth_user_id=auth_user_id,
            data=data,
            result=result,
        )
        return result

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
        replay_result = await self._maybe_replay_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="cancel_instance",
            data=data,
        )
        if replay_result is not None:
            return replay_result

        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status in self._TERMINAL_INSTANCE_STATUS:
            abort(409, "Completed/cancelled instances cannot be cancelled again.")

        now = self._now_utc()
        cancel_reason = self._normalize_optional_text(data.reason)
        cancel_note = self._normalize_optional_note(data.note)
        cancelled_decision_request_id: str | None = None

        decision_request = await self._find_open_decision_request(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            workflow_task_id=current.pending_task_id,
        )
        if decision_request is None:
            decision_request = await self._find_open_decision_request(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
            )
        if (
            decision_request is not None
            and decision_request.id is not None
            and int(decision_request.row_version or 0) > 0
        ):
            cancel_data = self._safe_decision_cancel_validation(
                row_version=int(decision_request.row_version or 0),
                reason=cancel_reason,
                note=cancel_note,
            )
            await self._decision_request_service.action_cancel(
                tenant_id=tenant_id,
                entity_id=decision_request.id,
                where={"tenant_id": tenant_id, "id": decision_request.id},
                auth_user_id=auth_user_id,
                data=cancel_data,
            )
            cancelled_decision_request_id = str(decision_request.id)

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
                "cancel_reason": cancel_reason,
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
            note=cancel_note,
            payload={
                "reason": cancel_reason,
                "decision_request_id": cancelled_decision_request_id,
                "status": "cancelled",
            },
        )

        result: tuple[dict[str, Any], int] = ("", 204)
        await self._record_action_result(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            action_name="cancel_instance",
            auth_user_id=auth_user_id,
            data=data,
            result=result,
        )
        return result

    async def action_replay(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowReplayValidation,
    ) -> tuple[dict[str, Any], int]:
        """Replay persisted events and optionally repair divergent instance state."""
        try:
            current = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if current is None:
            abort(404, "Workflow instance not found.")

        events = await self._ordered_events(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
        )
        derived = self._derive_state_from_events(events=events)

        divergence: dict[str, dict[str, Any]] = {}

        derived_status = self._normalize_optional_text(derived.get("status"))
        if derived_status is not None and derived_status != current.status:
            divergence["Status"] = {
                "Actual": current.status,
                "Derived": derived_status,
            }

        derived_state_id = derived.get("current_state_id")
        if not self._uuid_equal(derived_state_id, current.current_state_id):
            divergence["CurrentStateId"] = {
                "Actual": self._uuid_text(current.current_state_id),
                "Derived": self._uuid_text(derived_state_id),
            }

        derived_pending_task_id = derived.get("pending_task_id")
        if not self._uuid_equal(derived_pending_task_id, current.pending_task_id):
            divergence["PendingTaskId"] = {
                "Actual": self._uuid_text(current.pending_task_id),
                "Derived": self._uuid_text(derived_pending_task_id),
            }

        repaired = False
        if bool(data.repair) and divergence:
            await self.update(
                where=where,
                changes={
                    "status": derived_status or current.status,
                    "current_state_id": derived_state_id,
                    "pending_task_id": derived_pending_task_id,
                    "pending_transition_id": None,
                    "last_actor_user_id": auth_user_id,
                },
            )
            repaired = True

        await self._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            event_type="replayed",
            actor_user_id=auth_user_id,
            from_state_id=current.current_state_id,
            to_state_id=derived_state_id,
            payload={
                "repair": bool(data.repair),
                "repair_applied": repaired,
                "divergence_keys": list(divergence.keys()),
            },
        )

        return (
            {
                "DerivedState": {
                    "Status": derived_status,
                    "CurrentStateId": self._uuid_text(derived_state_id),
                    "PendingTaskId": self._uuid_text(derived_pending_task_id),
                },
                "Divergence": divergence,
                "RepairApplied": repaired,
                "EventCount": len(events),
            },
            200,
        )

    async def action_compensate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkflowCompensateValidation,
    ) -> tuple[dict[str, Any], int]:
        """Plan-only compensation event emission for transition compensation specs."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.workflow_version_id is None:
            abort(409, "Workflow instance is missing WorkflowVersionId.")

        transitions: list[WorkflowTransitionDE] = []
        if data.transition_key is not None:
            transitions = list(
                await self._transition_service.list(
                    filter_groups=[
                        FilterGroup(
                            where={
                                "tenant_id": tenant_id,
                                "workflow_version_id": current.workflow_version_id,
                                "key": data.transition_key.strip(),
                            }
                        )
                    ],
                    limit=20,
                )
            )
        elif current.pending_transition_id is not None:
            pending = await self._transition_service.get(
                {
                    "tenant_id": tenant_id,
                    "id": current.pending_transition_id,
                }
            )
            if pending is not None:
                transitions = [pending]
        elif current.current_state_id is not None:
            transitions = list(
                await self._transition_service.list(
                    filter_groups=[
                        FilterGroup(
                            where={
                                "tenant_id": tenant_id,
                                "workflow_version_id": current.workflow_version_id,
                                "from_state_id": current.current_state_id,
                                "is_active": True,
                            }
                        )
                    ],
                    limit=20,
                )
            )

        if not transitions:
            abort(409, "No transitions are eligible for compensation planning.")

        planned: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        await self._append_event(
            tenant_id=tenant_id,
            workflow_instance_id=entity_id,
            event_type="compensation_requested",
            actor_user_id=auth_user_id,
            from_state_id=current.current_state_id,
            to_state_id=current.current_state_id,
            note=data.note,
            payload={
                "execution_mode": "plan_only",
                "transition_count": len(transitions),
            },
        )

        for transition in transitions:
            transition_id = str(transition.id)
            transition_key = self._normalize_optional_text(transition.key)
            compensation = transition.compensation_json

            if not compensation:
                failure_item = {
                    "TransitionId": transition_id,
                    "TransitionKey": transition_key,
                    "Reason": "missing_compensation_spec",
                }
                failed.append(failure_item)
                await self._append_event(
                    tenant_id=tenant_id,
                    workflow_instance_id=entity_id,
                    event_type="compensation_failed",
                    actor_user_id=auth_user_id,
                    from_state_id=current.current_state_id,
                    to_state_id=current.current_state_id,
                    payload={
                        "execution_mode": "plan_only",
                        "transition_id": transition_id,
                        "transition_key": transition_key,
                        "reason": "missing_compensation_spec",
                    },
                )
                continue

            plan_item = {
                "TransitionId": transition_id,
                "TransitionKey": transition_key,
                "Compensation": compensation,
                "ExecutionMode": "plan_only",
            }
            planned.append(plan_item)
            await self._append_event(
                tenant_id=tenant_id,
                workflow_instance_id=entity_id,
                event_type="compensation_planned",
                actor_user_id=auth_user_id,
                from_state_id=current.current_state_id,
                to_state_id=current.current_state_id,
                payload={
                    "execution_mode": "plan_only",
                    "transition_id": transition_id,
                    "transition_key": transition_key,
                    "compensation": compensation,
                },
            )

        return (
            {
                "ExecutionMode": "plan_only",
                "Planned": planned,
                "Failed": failed,
            },
            200,
        )
