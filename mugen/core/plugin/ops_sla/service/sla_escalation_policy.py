"""Provides escalation policy evaluate/execute/test actions for ops_sla."""

__all__ = ["SlaEscalationPolicyService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.ops_sla.api.validation import (
    SlaEscalationEvaluateValidation,
    SlaEscalationExecuteValidation,
    SlaEscalationTestValidation,
)
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowDecisionRequestOpenValidation,
)
from mugen.core.plugin.ops_workflow.service.workflow_decision_request import (
    WorkflowDecisionRequestService,
)
from mugen.core.plugin.ops_sla.contract.service.sla_escalation_policy import (
    ISlaEscalationPolicyService,
)
from mugen.core.plugin.ops_sla.domain import SlaEscalationPolicyDE
from mugen.core.plugin.ops_sla.service.sla_escalation_run import SlaEscalationRunService


class SlaEscalationPolicyService(
    IRelationalService[SlaEscalationPolicyDE],
    ISlaEscalationPolicyService,
):
    """A CRUD/action service for deterministic escalation planning and run logging."""

    _RUN_TABLE = "ops_sla_escalation_run"
    _DECISION_REQUEST_TABLE = "ops_workflow_decision_request"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaEscalationPolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._run_service = SlaEscalationRunService(table=self._RUN_TABLE, rsg=rsg)
        self._decision_request_service = WorkflowDecisionRequestService(
            table=self._DECISION_REQUEST_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _parse_optional_uuid(cls, value: Any) -> uuid.UUID | None:
        if isinstance(value, uuid.UUID):
            return value
        if isinstance(value, str):
            clean = cls._normalize_optional_text(value)
            if clean is None:
                return None
            try:
                return uuid.UUID(clean)
            except ValueError:
                return None
        return None

    @classmethod
    def _parse_optional_datetime(cls, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        if isinstance(value, str):
            clean = cls._normalize_optional_text(value)
            if clean is None:
                return None
            try:
                parsed = datetime.fromisoformat(clean)
            except ValueError:
                return None
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        return None

    @staticmethod
    def _mapping_or_none(value: Any) -> dict[str, Any] | None:
        if isinstance(value, Mapping):
            return dict(value)
        return None

    @classmethod
    def _event_get(cls, payload: Mapping[str, Any], key: str) -> Any:
        direct = payload.get(key)
        if direct is not None:
            return direct

        key_lower = key.lower()
        for candidate_key, candidate_value in payload.items():
            if str(candidate_key).lower() == key_lower:
                return candidate_value
        return None

    @classmethod
    def _extract_path(cls, payload: Mapping[str, Any], path: str) -> Any:
        cursor: Any = payload
        for part in path.split("."):
            clean_part = cls._normalize_optional_text(part)
            if clean_part is None:
                return None
            if not isinstance(cursor, Mapping):
                return None
            cursor = cls._event_get(cursor, clean_part)
            if cursor is None:
                return None
        return cursor

    @staticmethod
    def _compare(op: str, actual: Any, expected: Any) -> bool:
        clean_op = (op or "eq").strip().lower()
        if clean_op == "ne":
            return actual != expected
        if clean_op == "in":
            if not isinstance(expected, list):
                return False
            return actual in expected
        if clean_op == "contains":
            if isinstance(actual, str) and isinstance(expected, str):
                return expected in actual
            if isinstance(actual, list):
                return expected in actual
            return False
        return actual == expected

    @classmethod
    def _matches_trigger(cls, event: Mapping[str, Any], trigger: Any) -> bool:
        if not isinstance(trigger, Mapping):
            return False

        any_rules = trigger.get("Any")
        if isinstance(any_rules, list) and any_rules:
            return any(cls._matches_trigger(event, item) for item in any_rules)

        all_rules = trigger.get("All")
        if isinstance(all_rules, list) and all_rules:
            return all(cls._matches_trigger(event, item) for item in all_rules)

        path = cls._normalize_optional_text(trigger.get("Path"))
        if path is not None:
            expected = trigger.get("Value")
            op = str(trigger.get("Op") or "eq")
            actual = cls._extract_path(event, path)
            return cls._compare(op, actual, expected)

        for key, expected in trigger.items():
            if str(key) in {"Any", "All", "Path", "Op", "Value"}:
                continue
            actual = cls._event_get(event, str(key))
            if actual != expected:
                return False

        return True

    @classmethod
    def _policy_matches_event(
        cls,
        *,
        policy: SlaEscalationPolicyDE,
        trigger_event: Mapping[str, Any],
    ) -> bool:
        triggers = policy.triggers_json or []
        if not triggers:
            return True
        return any(cls._matches_trigger(trigger_event, trigger) for trigger in triggers)

    @staticmethod
    def _policy_actions(policy: SlaEscalationPolicyDE) -> list[dict[str, Any]]:
        raw_actions = policy.actions_json or []
        actions: list[dict[str, Any]] = []
        for raw in raw_actions:
            if not isinstance(raw, Mapping):
                continue
            actions.append(dict(raw))
        return actions

    async def _load_policy_candidates(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        policy_key: str | None,
        entity_id: uuid.UUID | None,
    ) -> list[SlaEscalationPolicyDE]:
        if entity_id is not None:
            one = await self.get({"tenant_id": tenant_id, "id": entity_id})
            return [one] if one is not None else []

        where_id = where.get("id")
        if isinstance(where_id, uuid.UUID):
            one = await self.get({"tenant_id": tenant_id, "id": where_id})
            return [one] if one is not None else []

        clean_policy_key = self._normalize_optional_text(policy_key)
        if clean_policy_key is not None:
            one = await self.get(
                {"tenant_id": tenant_id, "policy_key": clean_policy_key}
            )
            return [one] if one is not None else []

        return list(
            await self.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "is_active": True,
                        }
                    )
                ],
                order_by=[
                    OrderBy(field="priority", descending=True),
                    OrderBy(field="created_at", descending=False),
                ],
            )
        )

    async def _evaluate_policies(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        policy_key: str | None,
        trigger_event_json: Mapping[str, Any],
        entity_id: uuid.UUID | None = None,
    ) -> tuple[list[SlaEscalationPolicyDE], list[dict[str, Any]]]:
        candidates = await self._load_policy_candidates(
            tenant_id=tenant_id,
            where=where,
            policy_key=policy_key,
            entity_id=entity_id,
        )

        matched_policies: list[SlaEscalationPolicyDE] = []
        planned_actions: list[dict[str, Any]] = []
        for policy in candidates:
            if not bool(policy.is_active):
                continue
            if not self._policy_matches_event(
                policy=policy,
                trigger_event=trigger_event_json,
            ):
                continue

            matched_policies.append(policy)
            for idx, action in enumerate(self._policy_actions(policy)):
                planned_actions.append(
                    {
                        "PolicyId": str(policy.id),
                        "PolicyKey": policy.policy_key,
                        "PolicyPriority": int(policy.priority or 0),
                        "ActionIndex": idx,
                        "Action": action,
                    }
                )

        return matched_policies, planned_actions

    @classmethod
    def _action_type(cls, action: Mapping[str, Any]) -> str | None:
        return cls._normalize_optional_text(
            action.get("ActionType") or action.get("Type")
        )

    @classmethod
    def _open_decision_payload(
        cls,
        *,
        trigger_event: Mapping[str, Any],
        policy: SlaEscalationPolicyDE,
        action: Mapping[str, Any],
    ) -> dict[str, Any]:
        template_key = cls._normalize_optional_text(
            action.get("TemplateKey") or action.get("template_key")
        )
        if template_key is None:
            template_key = "ops.sla.escalation.open_decision"

        trace_id = cls._normalize_optional_text(
            action.get("TraceId")
            or action.get("trace_id")
            or trigger_event.get("TraceId")
            or trigger_event.get("trace_id")
        )

        due_at = cls._parse_optional_datetime(
            action.get("DueAt")
            or action.get("due_at")
            or action.get("DueAtUtc")
            or action.get("due_at_utc")
        )
        if due_at is None:
            due_at = cls._parse_optional_datetime(
                trigger_event.get("DueAt") or trigger_event.get("due_at")
            )

        context = cls._mapping_or_none(
            action.get("ContextJson") or action.get("context_json")
        ) or {}
        context.setdefault("TriggerEvent", dict(trigger_event))
        context.setdefault(
            "EscalationPolicy",
            {
                "PolicyId": str(policy.id),
                "PolicyKey": policy.policy_key,
                "Priority": int(policy.priority or 0),
            },
        )

        return {
            "trace_id": trace_id,
            "template_key": template_key,
            "requester_actor_json": (
                cls._mapping_or_none(
                    action.get("RequesterActorJson")
                    or action.get("requester_actor_json")
                )
                or {"Source": "ops_sla_escalation"}
            ),
            "assigned_to_json": cls._mapping_or_none(
                action.get("AssignedToJson") or action.get("assigned_to_json")
            ),
            "options_json": cls._mapping_or_none(
                action.get("OptionsJson") or action.get("options_json")
            ),
            "context_json": context,
            "workflow_instance_id": cls._parse_optional_uuid(
                action.get("WorkflowInstanceId") or action.get("workflow_instance_id")
            ),
            "workflow_task_id": cls._parse_optional_uuid(
                action.get("WorkflowTaskId") or action.get("workflow_task_id")
            ),
            "due_at": due_at,
            "attributes": cls._mapping_or_none(
                action.get("Attributes") or action.get("attributes")
            ),
        }

    async def _action_result(
        self,
        *,
        action: Mapping[str, Any],
        dry_run: bool,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        trigger_event: Mapping[str, Any],
        policy: SlaEscalationPolicyDE,
    ) -> dict[str, Any]:
        action_type = self._action_type(action)
        if action_type is None:
            return {
                "ActionType": None,
                "Status": "invalid_action_type",
                "Code": "invalid_action_type",
                "Message": "ActionType must be non-empty.",
            }

        if action_type != "open_decision":
            return {
                "ActionType": action_type,
                "Status": "planned",
                "Code": "planned_downstream_adapter",
                "ExecutionMode": "plan_only",
            }

        open_payload = self._open_decision_payload(
            trigger_event=trigger_event,
            policy=policy,
            action=action,
        )
        if bool(dry_run):
            return {
                "ActionType": action_type,
                "Status": "planned",
                "Code": "planned_open_decision",
                "ExecutionMode": "plan_only",
                "OpenDecisionPayload": open_payload,
            }

        try:
            open_result, _status = await self._decision_request_service.action_open(
                tenant_id=tenant_id,
                where={"tenant_id": tenant_id},
                auth_user_id=auth_user_id,
                data=WorkflowDecisionRequestOpenValidation(**open_payload),
            )
        except HTTPException as error:
            return {
                "ActionType": action_type,
                "Status": "failed",
                "Code": "failed_open_decision",
                "Message": str(error.description or "open_decision execution failed"),
                "OpenDecisionPayload": open_payload,
            }
        except Exception as error:  # noqa: BLE001
            return {
                "ActionType": action_type,
                "Status": "failed",
                "Code": "failed_open_decision",
                "Message": str(error),
                "OpenDecisionPayload": open_payload,
            }

        return {
            "ActionType": action_type,
            "Status": "opened",
            "Code": "opened",
            "DecisionRequestId": (
                str(open_result.get("DecisionRequestId"))
                if isinstance(open_result, Mapping)
                and open_result.get("DecisionRequestId") is not None
                else None
            ),
            "OpenDecisionPayload": open_payload,
        }

    @staticmethod
    def _aggregate_run_status(results: list[dict[str, Any]]) -> str:
        if not results:
            return "noop"

        statuses = [str(result.get("Status") or "") for result in results]
        if any(status == "invalid_action_type" for status in statuses):
            return "failed"

        has_failed_open_decision = any(
            str(result.get("Code") or "") == "failed_open_decision"
            for result in results
        )
        has_failed = has_failed_open_decision or any(
            status == "failed" for status in statuses
        )
        has_success = any(status in {"planned", "opened"} for status in statuses)

        if has_failed and has_success:
            return "partial"
        if has_failed:
            return "failed"
        return "ok"

    async def action_evaluate(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: SlaEscalationEvaluateValidation,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate trigger payload against active escalation policies."""
        if not isinstance(data.trigger_event_json, Mapping):
            abort(400, "TriggerEventJson must be an object.")

        matched, actions = await self._evaluate_policies(
            tenant_id=tenant_id,
            where=where,
            policy_key=data.policy_key,
            trigger_event_json=dict(data.trigger_event_json),
            entity_id=entity_id,
        )

        return (
            {
                "MatchedPolicyCount": len(matched),
                "MatchedPolicyIds": [str(policy.id) for policy in matched],
                "Actions": actions,
            },
            200,
        )

    async def action_execute(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: SlaEscalationExecuteValidation,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate and persist escalation run rows with per-action diagnostics."""
        if not isinstance(data.trigger_event_json, Mapping):
            abort(400, "TriggerEventJson must be an object.")

        trigger_event = dict(data.trigger_event_json)
        matched_policies, _planned_actions = await self._evaluate_policies(
            tenant_id=tenant_id,
            where=where,
            policy_key=data.policy_key,
            trigger_event_json=trigger_event,
            entity_id=entity_id,
        )

        if not matched_policies:
            return (
                {
                    "RunId": None,
                    "Status": "noop",
                    "MatchedPolicyCount": 0,
                    "Runs": [],
                },
                200,
            )

        runs: list[dict[str, Any]] = []
        for policy in matched_policies:
            action_results: list[dict[str, Any]] = []
            for action in self._policy_actions(policy):
                action_results.append(
                    await self._action_result(
                        action=action,
                        dry_run=bool(data.dry_run),
                        tenant_id=tenant_id,
                        auth_user_id=auth_user_id,
                        trigger_event=trigger_event,
                        policy=policy,
                    )
                )
            status = self._aggregate_run_status(action_results)

            run_id: str | None = None
            if not bool(data.dry_run):
                created = await self._run_service.create(
                    {
                        "tenant_id": tenant_id,
                        "escalation_policy_id": policy.id,
                        "clock_id": trigger_event.get("ClockId")
                        or trigger_event.get("clock_id"),
                        "clock_event_id": trigger_event.get("ClockEventId")
                        or trigger_event.get("clock_event_id"),
                        "status": status,
                        "trigger_event_json": trigger_event,
                        "results_json": action_results,
                        "trace_id": self._normalize_optional_text(
                            trigger_event.get("TraceId")
                            or trigger_event.get("trace_id")
                        ),
                        "executed_by_user_id": auth_user_id,
                    }
                )
                run_id = str(created.id)

            runs.append(
                {
                    "PolicyId": str(policy.id),
                    "PolicyKey": policy.policy_key,
                    "RunId": run_id,
                    "Status": status,
                    "Results": action_results,
                }
            )

        first_status = runs[0]["Status"] if runs else "noop"
        first_run_id = runs[0]["RunId"] if runs else None
        return (
            {
                "RunId": first_run_id,
                "Status": first_status,
                "MatchedPolicyCount": len(matched_policies),
                "Runs": runs,
            },
            200,
        )

    async def action_test(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: SlaEscalationTestValidation,
        entity_id: uuid.UUID | None = None,  # noqa: ARG002
    ) -> tuple[dict[str, Any], int]:
        """Test one policy against one sample event payload."""
        policy = await self.get(
            {
                "tenant_id": tenant_id,
                "policy_key": data.policy_key.strip(),
            }
        )
        if policy is None:
            abort(404, "Escalation policy not found.")

        sample_event = dict(data.sample_event_json)
        matched = self._policy_matches_event(policy=policy, trigger_event=sample_event)
        would_execute: list[dict[str, Any]] = []
        if matched:
            for action in self._policy_actions(policy):
                would_execute.append(
                    {
                        "Action": action,
                        "Result": await self._action_result(
                            action=action,
                            dry_run=True,
                            tenant_id=tenant_id,
                            auth_user_id=auth_user_id,
                            trigger_event=sample_event,
                            policy=policy,
                        ),
                    }
                )

        return (
            {
                "PolicyId": str(policy.id),
                "PolicyKey": policy.policy_key,
                "Matched": matched,
                "WouldExecute": would_execute,
            },
            200,
        )
