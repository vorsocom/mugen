"""Runtime services for the agent_runtime plugin."""

from __future__ import annotations

__all__ = [
    "ACPActionCapabilityProvider",
    "AgentPlanRunService",
    "AgentPlanStepService",
    "AllowlistExecutionGuard",
    "CodeConfiguredAgentPolicyResolver",
    "LLMEvaluationStrategy",
    "LLMPlannerStrategy",
    "RelationalAgentScheduler",
    "RelationalPlanRunStore",
    "TextResponseSynthesizer",
]

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import inspect
import json
from types import SimpleNamespace
from typing import Any
import uuid

from mugen.core.contract.agent import (
    AgentRuntimePolicy,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityResult,
    JoinPolicy,
    JoinState,
    EvaluationRequest,
    EvaluationResult,
    EvaluationStatus,
    IAgentPolicyResolver,
    IAgentScheduler,
    ICapabilityProvider,
    IEvaluatorStrategy,
    IExecutionGuard,
    IPlanRunStore,
    IPlannerStrategy,
    IResponseSynthesizer,
    PlanDecision,
    PlanDecisionKind,
    PlanLease,
    PlanObservation,
    PlanOutcome,
    PlanOutcomeStatus,
    PlanRunCursor,
    PlanRunLineage,
    PlanRunMode,
    PlanRunRequest,
    PlanRunState,
    PlanRunStatus,
    PlanRunStep,
    PreparedPlanRun,
)
from mugen.core.contract.context import ContextScope
from mugen.core.contract.gateway.completion import (
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
    CompletionResponse,
    ICompletionGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.agent_runtime.domain import AgentPlanRunDE, AgentPlanStepDE
from mugen.core.utility.config_value import parse_bool_flag, parse_optional_positive_int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _uuid_or_none(value: object) -> uuid.UUID | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    return uuid.UUID(normalized)


def _scope_key(scope: ContextScope) -> str:
    parts = [
        scope.tenant_id,
        scope.platform or "*",
        scope.channel_id or "*",
        scope.room_id or "*",
        scope.sender_id or "*",
        scope.conversation_id or "*",
        scope.case_id or "*",
        scope.workflow_id or "*",
    ]
    return ":".join(parts)


def _scope_to_dict(scope: ContextScope) -> dict[str, Any]:
    return asdict(scope)


def _request_snapshot(request: PlanRunRequest) -> dict[str, Any]:
    return {
        "mode": request.mode.value,
        "scope": _scope_to_dict(request.scope),
        "user_message": request.user_message,
        "message_id": request.message_id,
        "trace_id": request.trace_id,
        "service_route_key": request.service_route_key,
        "agent_key": request.agent_key,
        "ingress_metadata": dict(request.ingress_metadata),
        "metadata": dict(request.metadata),
    }


def _serialize_lineage(lineage: PlanRunLineage | None) -> dict[str, Any] | None:
    if lineage is None:
        return None
    return {
        "parent_run_id": lineage.parent_run_id,
        "root_run_id": lineage.root_run_id,
        "spawned_by_step_no": lineage.spawned_by_step_no,
        "agent_key": lineage.agent_key,
    }


def _deserialize_lineage(payload: dict[str, Any] | None) -> PlanRunLineage | None:
    if not isinstance(payload, dict):
        return None
    return PlanRunLineage(
        parent_run_id=_normalize_optional_text(payload.get("parent_run_id")),
        root_run_id=_normalize_optional_text(payload.get("root_run_id")),
        spawned_by_step_no=payload.get("spawned_by_step_no"),
        agent_key=_normalize_optional_text(payload.get("agent_key")),
    )


def _serialize_join_policy(policy: JoinPolicy | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "mode": policy.mode.value,
        "on_required_child_failed": policy.on_required_child_failed.value,
        "on_required_child_handoff": policy.on_required_child_handoff.value,
        "on_required_child_stopped": policy.on_required_child_stopped.value,
        "metadata": dict(policy.metadata),
    }


def _deserialize_join_policy(payload: dict[str, Any] | None) -> JoinPolicy | None:
    if not isinstance(payload, dict):
        return None
    return JoinPolicy(
        mode=str(payload.get("mode") or "all_required"),
        on_required_child_failed=str(
            payload.get("on_required_child_failed") or PlanOutcomeStatus.HANDOFF.value
        ),
        on_required_child_handoff=str(
            payload.get("on_required_child_handoff") or PlanOutcomeStatus.HANDOFF.value
        ),
        on_required_child_stopped=str(
            payload.get("on_required_child_stopped") or PlanOutcomeStatus.HANDOFF.value
        ),
        metadata=dict(payload.get("metadata") or {}),
    )


def _serialize_join_state(join_state: JoinState | None) -> dict[str, Any] | None:
    if join_state is None:
        return None
    return {
        "child_run_ids": list(join_state.child_run_ids),
        "required_child_run_ids": list(join_state.required_child_run_ids),
        "completed_child_run_ids": list(join_state.completed_child_run_ids),
        "last_joined_sequence_no": join_state.last_joined_sequence_no,
        "timeout_at": None if join_state.timeout_at is None else join_state.timeout_at.isoformat(),
        "policy": _serialize_join_policy(join_state.policy),
        "metadata": dict(join_state.metadata),
    }


def _deserialize_join_state(payload: dict[str, Any] | None) -> JoinState | None:
    if not isinstance(payload, dict):
        return None
    timeout_at = payload.get("timeout_at")
    if isinstance(timeout_at, str) and timeout_at != "":
        timeout_value = datetime.fromisoformat(timeout_at)
    else:
        timeout_value = None
    return JoinState(
        child_run_ids=tuple(payload.get("child_run_ids") or ()),
        required_child_run_ids=tuple(payload.get("required_child_run_ids") or ()),
        completed_child_run_ids=tuple(payload.get("completed_child_run_ids") or ()),
        last_joined_sequence_no=int(payload.get("last_joined_sequence_no") or 0),
        timeout_at=timeout_value,
        policy=_deserialize_join_policy(payload.get("policy")) or JoinPolicy(),
        metadata=dict(payload.get("metadata") or {}),
    )


def _serialize_policy(policy: AgentRuntimePolicy) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "current_turn_enabled": policy.current_turn_enabled,
        "background_enabled": policy.background_enabled,
        "agent_key": policy.agent_key,
        "planner_key": policy.planner_key,
        "evaluator_key": policy.evaluator_key,
        "response_synthesizer_key": policy.response_synthesizer_key,
        "capability_allow": list(policy.capability_allow),
        "delegate_agent_allow": list(policy.delegate_agent_allow),
        "max_iterations": policy.max_iterations,
        "max_background_iterations": policy.max_background_iterations,
        "lease_seconds": policy.lease_seconds,
        "wait_seconds_default": policy.wait_seconds_default,
        "metadata": dict(policy.metadata),
    }


def _deserialize_policy(payload: dict[str, Any] | None) -> AgentRuntimePolicy:
    payload = dict(payload or {})
    return AgentRuntimePolicy(
        enabled=bool(payload.get("enabled", False)),
        current_turn_enabled=bool(payload.get("current_turn_enabled", False)),
        background_enabled=bool(payload.get("background_enabled", False)),
        agent_key=_normalize_optional_text(payload.get("agent_key")),
        planner_key=str(payload.get("planner_key") or "llm_default"),
        evaluator_key=str(payload.get("evaluator_key") or "llm_default"),
        response_synthesizer_key=str(
            payload.get("response_synthesizer_key") or "text_default"
        ),
        capability_allow=tuple(payload.get("capability_allow") or ()),
        delegate_agent_allow=tuple(payload.get("delegate_agent_allow") or ()),
        max_iterations=int(payload.get("max_iterations") or 4),
        max_background_iterations=int(payload.get("max_background_iterations") or 8),
        lease_seconds=int(payload.get("lease_seconds") or 60),
        wait_seconds_default=int(payload.get("wait_seconds_default") or 30),
        metadata=dict(payload.get("metadata") or {}),
    )


def _serialize_state(state: PlanRunState) -> dict[str, Any]:
    return {
        "goal": state.goal,
        "status": state.status.value,
        "iteration_count": state.iteration_count,
        "background_iteration_count": state.background_iteration_count,
        "last_response_text": state.last_response_text,
        "last_error": state.last_error,
        "summary": state.summary,
        "metadata": dict(state.metadata),
    }


def _deserialize_state(payload: dict[str, Any] | None) -> PlanRunState:
    payload = dict(payload or {})
    return PlanRunState(
        goal=str(payload.get("goal") or ""),
        status=PlanRunStatus(str(payload.get("status") or PlanRunStatus.PREPARED.value)),
        iteration_count=int(payload.get("iteration_count") or 0),
        background_iteration_count=int(payload.get("background_iteration_count") or 0),
        last_response_text=_normalize_optional_text(payload.get("last_response_text")),
        last_error=_normalize_optional_text(payload.get("last_error")),
        summary=_normalize_optional_text(payload.get("summary")),
        metadata=dict(payload.get("metadata") or {}),
    )


def _serialize_outcome(outcome: PlanOutcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    return {
        "status": outcome.status.value,
        "final_user_responses": [dict(item) for item in outcome.final_user_responses],
        "assistant_response": outcome.assistant_response,
        "completion": _serialize_completion(outcome.completion),
        "background_run_id": outcome.background_run_id,
        "error_message": outcome.error_message,
        "metadata": dict(outcome.metadata),
    }


def _deserialize_outcome(payload: dict[str, Any] | None) -> PlanOutcome | None:
    if not isinstance(payload, dict):
        return None
    return PlanOutcome(
        status=PlanOutcomeStatus(str(payload.get("status") or PlanOutcomeStatus.FAILED.value)),
        final_user_responses=tuple(payload.get("final_user_responses") or ()),
        assistant_response=_normalize_optional_text(payload.get("assistant_response")),
        completion=_deserialize_completion(payload.get("completion")),
        background_run_id=_normalize_optional_text(payload.get("background_run_id")),
        error_message=_normalize_optional_text(payload.get("error_message")),
        metadata=dict(payload.get("metadata") or {}),
    )


def _serialize_completion(completion: CompletionResponse | None) -> dict[str, Any] | None:
    if completion is None:
        return None
    usage = None
    if completion.usage is not None:
        usage = {
            "input_tokens": completion.usage.input_tokens,
            "output_tokens": completion.usage.output_tokens,
            "total_tokens": completion.usage.total_tokens,
            "vendor_fields": dict(completion.usage.vendor_fields),
        }
    return {
        "content": completion.content,
        "model": completion.model,
        "stop_reason": completion.stop_reason,
        "message": dict(completion.message or {}) if completion.message else None,
        "tool_calls": [dict(item) for item in completion.tool_calls],
        "usage": usage,
        "vendor_fields": dict(completion.vendor_fields),
    }


def _deserialize_completion(payload: dict[str, Any] | None) -> CompletionResponse | None:
    if not isinstance(payload, dict):
        return None
    usage_payload = payload.get("usage")
    usage = None
    if isinstance(usage_payload, dict):
        from mugen.core.contract.gateway.completion import CompletionUsage

        usage = CompletionUsage(
            input_tokens=usage_payload.get("input_tokens"),
            output_tokens=usage_payload.get("output_tokens"),
            total_tokens=usage_payload.get("total_tokens"),
            vendor_fields=dict(usage_payload.get("vendor_fields") or {}),
        )
    return CompletionResponse(
        content=payload.get("content"),
        model=_normalize_optional_text(payload.get("model")),
        stop_reason=_normalize_optional_text(payload.get("stop_reason")),
        message=dict(payload.get("message") or {}) if payload.get("message") else None,
        tool_calls=list(payload.get("tool_calls") or ()),
        usage=usage,
        vendor_fields=dict(payload.get("vendor_fields") or {}),
    )


def _parse_json_object(text: str | None) -> dict[str, Any] | None:
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if candidate == "":
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _coerce_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=True, sort_keys=True)


def _tool_spec(descriptor: CapabilityDescriptor) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": descriptor.key,
            "description": descriptor.description or descriptor.title,
            "parameters": descriptor.input_schema
            or {"type": "object", "properties": {}, "additionalProperties": True},
        },
    }


def _merge_vendor_tools(
    *,
    vendor_params: dict[str, Any],
    capabilities: tuple[CapabilityDescriptor, ...],
) -> dict[str, Any]:
    merged = dict(vendor_params)
    if capabilities:
        merged["tools"] = [_tool_spec(item) for item in capabilities]
        merged.setdefault("tool_choice", "auto")
        merged.setdefault("parallel_tool_calls", False)
    return merged


def _tool_call_invocations(tool_calls: list[dict[str, Any]]) -> tuple[CapabilityInvocation, ...]:
    invocations: list[CapabilityInvocation] = []
    for tool_call in tool_calls:
        function_payload = tool_call.get("function")
        if isinstance(function_payload, dict):
            capability_key = _normalize_optional_text(function_payload.get("name"))
            raw_arguments = function_payload.get("arguments")
        else:
            capability_key = _normalize_optional_text(tool_call.get("name"))
            raw_arguments = tool_call.get("arguments")
        if capability_key is None:
            continue
        if isinstance(raw_arguments, str):
            try:
                parsed_arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                parsed_arguments = {}
        else:
            parsed_arguments = raw_arguments
        arguments = parsed_arguments if isinstance(parsed_arguments, dict) else {}
        invocations.append(
            CapabilityInvocation(
                capability_key=capability_key,
                arguments=arguments,
                idempotency_key=_normalize_optional_text(tool_call.get("id")),
            )
        )
    return tuple(invocations)


class AgentPlanRunService(IRelationalService[AgentPlanRunDE]):  # pylint: disable=too-few-public-methods
    """CRUD service for plan-run rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(de_type=AgentPlanRunDE, table=table, rsg=rsg, **kwargs)


class AgentPlanStepService(IRelationalService[AgentPlanStepDE]):  # pylint: disable=too-few-public-methods
    """CRUD service for append-only plan-step rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(de_type=AgentPlanStepDE, table=table, rsg=rsg, **kwargs)


class CodeConfiguredAgentPolicyResolver(IAgentPolicyResolver):
    """Resolve route-scoped agent-runtime policy from runtime config."""

    def __init__(self, *, config: SimpleNamespace) -> None:
        self._config = config

    async def resolve_policy(self, request: PlanRunRequest) -> AgentRuntimePolicy:
        cfg = _cfg_section(getattr(self._config, "mugen", None), "agent_runtime")
        if cfg is None:
            return AgentRuntimePolicy()

        defaults = self._policy_from_config(cfg)
        route_cfg = self._route_config(cfg, request.service_route_key)
        requested_agent_key = _normalize_optional_text(request.agent_key)
        route_agent_key = None
        if route_cfg is not None:
            route_agent_key = _normalize_optional_text(_cfg_value(route_cfg, "agent_key"))
        selected_agent_key = requested_agent_key or route_agent_key or defaults.agent_key

        policy = defaults
        agent_cfg = self._agent_config(cfg, selected_agent_key)
        if agent_cfg is not None:
            policy = self._policy_from_config(agent_cfg, base=policy)
        elif selected_agent_key is not None:
            policy.agent_key = selected_agent_key

        if route_cfg is not None:
            policy = self._policy_from_config(route_cfg, base=policy)

        resolved_route_key = request.service_route_key
        if resolved_route_key is None and route_cfg is not None:
            resolved_route_key = _normalize_optional_text(
                _cfg_value(route_cfg, "service_route_key")
            )
        if resolved_route_key is None and agent_cfg is not None:
            resolved_route_key = _normalize_optional_text(
                _cfg_value(agent_cfg, "service_route_key")
            )

        policy.agent_key = selected_agent_key or policy.agent_key
        policy.metadata = dict(policy.metadata)
        policy.metadata["service_route_key"] = resolved_route_key
        if selected_agent_key is not None and agent_cfg is None:
            policy.metadata["agent_definition_missing"] = selected_agent_key
        return policy

    @staticmethod
    def _route_config(cfg: Any, service_route_key: str | None) -> Any | None:
        normalized_route = _normalize_optional_text(service_route_key)
        for route_cfg in _cfg_list(cfg, "routes"):
            if _normalize_optional_text(_cfg_value(route_cfg, "service_route_key")) != normalized_route:
                continue
            return route_cfg
        return None

    @staticmethod
    def _agent_config(cfg: Any, agent_key: str | None) -> Any | None:
        normalized_agent_key = _normalize_optional_text(agent_key)
        if normalized_agent_key is None:
            return None
        for agent_cfg in _cfg_list(cfg, "agents"):
            if _normalize_optional_text(_cfg_value(agent_cfg, "agent_key")) != normalized_agent_key:
                continue
            return agent_cfg
        return None

    def _policy_from_config(
        self,
        cfg: Any,
        *,
        base: AgentRuntimePolicy | None = None,
    ) -> AgentRuntimePolicy:
        seed = base or AgentRuntimePolicy()
        enabled = parse_bool_flag(_cfg_value(cfg, "enabled"), seed.enabled)
        current_turn_enabled = parse_bool_flag(
            _cfg_value(cfg, "current_turn_enabled"),
            seed.current_turn_enabled if base is not None else enabled,
        )
        background_enabled = parse_bool_flag(
            _cfg_value(cfg, "background_enabled"),
            seed.background_enabled if base is not None else enabled,
        )
        max_iterations = parse_optional_positive_int(
            _cfg_value(cfg, "max_iterations"),
            "mugen.agent_runtime.max_iterations",
        )
        max_background_iterations = parse_optional_positive_int(
            _cfg_value(cfg, "max_background_iterations"),
            "mugen.agent_runtime.max_background_iterations",
        )
        lease_seconds = parse_optional_positive_int(
            _cfg_value(cfg, "lease_seconds"),
            "mugen.agent_runtime.lease_seconds",
        )
        wait_seconds_default = parse_optional_positive_int(
            _cfg_value(cfg, "wait_seconds_default"),
            "mugen.agent_runtime.wait_seconds_default",
        )
        capability_allow = tuple(
            item
            for item in (
                _normalize_optional_text(value)
                for value in _cfg_list(cfg, "capability_allow")
            )
            if item is not None
        )
        delegate_agent_allow = tuple(
            item
            for item in (
                _normalize_optional_text(value)
                for value in _cfg_list(cfg, "delegate_agent_allow")
            )
            if item is not None
        )
        return AgentRuntimePolicy(
            enabled=enabled,
            current_turn_enabled=current_turn_enabled,
            background_enabled=background_enabled,
            agent_key=_normalize_optional_text(_cfg_value(cfg, "agent_key")) or seed.agent_key,
            planner_key=str(_cfg_value(cfg, "planner_key") or seed.planner_key),
            evaluator_key=str(_cfg_value(cfg, "evaluator_key") or seed.evaluator_key),
            response_synthesizer_key=str(
                _cfg_value(cfg, "response_synthesizer_key")
                or seed.response_synthesizer_key
            ),
            capability_allow=capability_allow or seed.capability_allow,
            delegate_agent_allow=delegate_agent_allow or seed.delegate_agent_allow,
            max_iterations=max_iterations or seed.max_iterations,
            max_background_iterations=(
                max_background_iterations or seed.max_background_iterations
            ),
            lease_seconds=lease_seconds or seed.lease_seconds,
            wait_seconds_default=wait_seconds_default or seed.wait_seconds_default,
            metadata=dict(seed.metadata),
        )


class LLMPlannerStrategy(IPlannerStrategy):
    """LLM-first planner that reuses the normalized completion gateway."""

    name = "llm_default"

    def __init__(
        self,
        *,
        completion_gateway: ICompletionGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._completion_gateway = completion_gateway
        self._logging_gateway = logging_gateway

    async def next_decision(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        observations: tuple[PlanObservation, ...],
        *,
        policy: AgentRuntimePolicy,
    ) -> PlanDecision:
        completion_request = self._completion_request(
            request=request,
            run=run,
            observations=observations,
        )
        completion = await self._completion_gateway.get_completion(completion_request)
        invocations = _tool_call_invocations(list(completion.tool_calls))
        if invocations:
            return PlanDecision(
                kind=PlanDecisionKind.EXECUTE_ACTION,
                capability_invocations=invocations,
                completion=completion,
                rationale_summary="tool_calls_requested",
            )
        return PlanDecision(
            kind=PlanDecisionKind.RESPOND,
            response_text=_coerce_to_text(completion.content),
            completion=completion,
            rationale_summary="response_ready",
        )

    async def finalize_run(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        outcome: PlanOutcome,
        *,
        policy: AgentRuntimePolicy,
    ) -> None:
        _ = (request, run, outcome, policy)
        return None

    def _completion_request(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        observations: tuple[PlanObservation, ...],
    ) -> CompletionRequest:
        capabilities = tuple(request.available_capabilities or ())
        if request.prepared_context is not None and not observations:
            base = request.prepared_context.completion_request
            return CompletionRequest(
                messages=list(base.messages),
                operation=base.operation,
                model=base.model,
                inference=base.inference,
                vendor_params=_merge_vendor_tools(
                    vendor_params=dict(base.vendor_params),
                    capabilities=capabilities,
                ),
            )

        if request.prepared_context is not None:
            base = request.prepared_context.completion_request
            messages = list(base.messages)
            messages.append(
                CompletionMessage(
                    role="user",
                    content={
                        "agent_observations": [self._observation_payload(item) for item in observations],
                        "instruction": "Continue using tools if needed, otherwise respond to the user.",
                    },
                )
            )
            return CompletionRequest(
                messages=messages,
                operation=base.operation,
                model=base.model,
                inference=base.inference,
                vendor_params=_merge_vendor_tools(
                    vendor_params=dict(base.vendor_params),
                    capabilities=capabilities,
                ),
            )

        messages = [
            CompletionMessage(
                role="system",
                content=(
                    "You are a planning engine. Use tools when needed. "
                    "When no tool is needed, answer the user directly."
                ),
            ),
            CompletionMessage(
                role="user",
                content={
                    "goal": request.user_message,
                    "service_route_key": request.service_route_key,
                    "run_state": _serialize_state(run.state),
                    "observations": [self._observation_payload(item) for item in observations],
                },
            ),
        ]
        return CompletionRequest(
            messages=messages,
            operation="completion",
            inference=CompletionInferenceConfig(temperature=0.1),
            vendor_params=_merge_vendor_tools(
                vendor_params={},
                capabilities=capabilities,
            ),
        )

    @staticmethod
    def _observation_payload(observation: PlanObservation) -> dict[str, Any]:
        payload = {
            "kind": observation.kind,
            "summary": observation.summary,
            "payload": dict(observation.payload),
            "success": observation.success,
        }
        if observation.capability_result is not None:
            payload["capability_result"] = {
                "capability_key": observation.capability_result.capability_key,
                "ok": observation.capability_result.ok,
                "status_code": observation.capability_result.status_code,
                "error_message": observation.capability_result.error_message,
                "result": observation.capability_result.result,
            }
        return payload


class LLMEvaluationStrategy(IEvaluatorStrategy):
    """LLM-first evaluator with deterministic fallback semantics."""

    name = "llm_default"

    def __init__(
        self,
        *,
        completion_gateway: ICompletionGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._completion_gateway = completion_gateway
        self._logging_gateway = logging_gateway

    async def evaluate_step(
        self,
        request: EvaluationRequest,
        *,
        policy: AgentRuntimePolicy,
    ) -> EvaluationResult:
        failure = next(
            (
                item.capability_result
                for item in request.observations
                if item.capability_result is not None and item.capability_result.ok is False
            ),
            None,
        )
        if failure is None:
            return EvaluationResult(status=EvaluationStatus.PASS)
        prompted = await self._prompt_evaluator(
            {
                "stage": "step",
                "goal": request.request.user_message,
                "failure": {
                    "capability_key": failure.capability_key,
                    "error_message": failure.error_message,
                    "status_code": failure.status_code,
                },
            }
        )
        if prompted is not None:
            return prompted
        return EvaluationResult(
            status=EvaluationStatus.REPLAN,
            reasons=(failure.error_message or "capability_failed",),
        )

    async def evaluate_response(
        self,
        request: EvaluationRequest,
        *,
        policy: AgentRuntimePolicy,
    ) -> EvaluationResult:
        if _normalize_optional_text(request.draft_response_text) is None:
            return EvaluationResult(
                status=EvaluationStatus.RETRY,
                reasons=("blank_response",),
            )
        prompted = await self._prompt_evaluator(
            {
                "stage": "response",
                "goal": request.request.user_message,
                "response": request.draft_response_text,
                "observations": [item.payload for item in request.observations],
            }
        )
        if prompted is not None:
            return prompted
        return EvaluationResult(status=EvaluationStatus.PASS)

    async def evaluate_run(
        self,
        request: EvaluationRequest,
        outcome: PlanOutcome,
        *,
        policy: AgentRuntimePolicy,
    ) -> EvaluationResult:
        if outcome.status == PlanOutcomeStatus.FAILED:
            return EvaluationResult(
                status=EvaluationStatus.ESCALATE,
                reasons=(outcome.error_message or "run_failed",),
            )
        prompted = await self._prompt_evaluator(
            {
                "stage": "run",
                "goal": request.request.user_message,
                "outcome": _serialize_outcome(outcome),
            }
        )
        if prompted is not None:
            return prompted
        return EvaluationResult(status=EvaluationStatus.PASS)

    async def _prompt_evaluator(
        self,
        payload: dict[str, Any],
    ) -> EvaluationResult | None:
        try:
            completion = await self._completion_gateway.get_completion(
                CompletionRequest(
                    messages=[
                        CompletionMessage(
                            role="system",
                            content=(
                                "Return JSON only with keys status and reasons. "
                                "status must be one of: pass, fail, retry, replan, escalate."
                            ),
                        ),
                        CompletionMessage(role="user", content=payload),
                    ],
                    operation="completion",
                    inference=CompletionInferenceConfig(temperature=0.0),
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Agent evaluator model call failed "
                f"(error={type(exc).__name__}: {exc})."
            )
            return None

        parsed = _parse_json_object(_coerce_to_text(completion.content))
        if parsed is None:
            return None
        status = _normalize_optional_text(parsed.get("status"))
        if status not in {item.value for item in EvaluationStatus}:
            return None
        reasons = parsed.get("reasons")
        if isinstance(reasons, list):
            normalized_reasons = tuple(
                item
                for item in (_normalize_optional_text(reason) for reason in reasons)
                if item is not None
            )
        else:
            normalized_reasons = ()
        recommended = _normalize_optional_text(parsed.get("recommended_decision"))
        return EvaluationResult(
            status=EvaluationStatus(status),
            reasons=normalized_reasons,
            recommended_decision=(
                None if recommended is None else PlanDecisionKind(recommended)
            ),
        )


class ACPActionCapabilityProvider(ICapabilityProvider):
    """Expose ACP resource actions through normalized capability descriptors."""

    name = "acp_actions"

    _prefix = "acp__"

    def __init__(
        self,
        *,
        admin_registry: IAdminRegistry | None,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._admin_registry = admin_registry
        self._logging_gateway = logging_gateway

    async def list_capabilities(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        *,
        policy: AgentRuntimePolicy,
    ) -> list[CapabilityDescriptor]:
        _ = (request, run, policy)
        if self._admin_registry is None:
            return []
        descriptors: list[CapabilityDescriptor] = []
        for resource in self._admin_registry.resources.values():
            actions = getattr(resource.capabilities, "actions", {}) or {}
            service = self._admin_registry.get_edm_service(resource.service_key)
            for action_name, action_cap in actions.items():
                schema = action_cap.get("schema") if isinstance(action_cap, dict) else None
                if schema is None:
                    continue
                descriptor = self._descriptor_from_action(
                    resource=resource,
                    service=service,
                    action_name=str(action_name),
                    schema=schema,
                )
                if descriptor is not None:
                    descriptors.append(descriptor)
        return descriptors

    def supports(self, capability_key: str) -> bool:
        return capability_key.startswith(self._prefix)

    async def execute(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        invocation: CapabilityInvocation,
        descriptor: CapabilityDescriptor,
        *,
        policy: AgentRuntimePolicy,
    ) -> CapabilityResult:
        _ = (run, policy)
        if self._admin_registry is None:
            return CapabilityResult(
                capability_key=invocation.capability_key,
                ok=False,
                error_message="admin_registry_unavailable",
            )
        entity_set = descriptor.metadata.get("entity_set")
        action_name = descriptor.metadata.get("action_name")
        if not isinstance(entity_set, str) or not isinstance(action_name, str):
            return CapabilityResult(
                capability_key=invocation.capability_key,
                ok=False,
                error_message="invalid_capability_metadata",
            )

        resource = self._admin_registry.get_resource(entity_set)
        service = self._admin_registry.get_edm_service(resource.service_key)
        handler = getattr(service, f"action_{action_name}", None)
        if handler is None or not callable(handler):
            return CapabilityResult(
                capability_key=invocation.capability_key,
                ok=False,
                error_message="capability_handler_missing",
            )

        arguments = dict(invocation.arguments)
        entity_id = arguments.pop("entity_id", arguments.pop("id", None))
        auth_user_id = arguments.pop("auth_user_id", request.metadata.get("auth_user_id"))
        if auth_user_id is None:
            auth_user_id = request.scope.sender_id
        schema = descriptor.metadata.get("schema")
        try:
            validated = schema.model_validate(arguments) if schema is not None else arguments
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return CapabilityResult(
                capability_key=invocation.capability_key,
                ok=False,
                error_message=f"validation_failed:{exc}",
            )

        kwargs = {}
        signature = inspect.signature(handler)
        if "tenant_id" in signature.parameters:
            kwargs["tenant_id"] = uuid.UUID(request.scope.tenant_id)
        if "entity_id" in signature.parameters:
            normalized_entity_id = _normalize_optional_text(entity_id)
            if normalized_entity_id is None:
                return CapabilityResult(
                    capability_key=invocation.capability_key,
                    ok=False,
                    error_message="entity_id_required",
                )
            kwargs["entity_id"] = uuid.UUID(normalized_entity_id)
        if "where" in signature.parameters:
            where = {"tenant_id": uuid.UUID(request.scope.tenant_id)}
            if "entity_id" in kwargs:
                where["id"] = kwargs["entity_id"]
            kwargs["where"] = where
        if "auth_user_id" in signature.parameters:
            normalized_auth = _normalize_optional_text(auth_user_id)
            if normalized_auth is None:
                return CapabilityResult(
                    capability_key=invocation.capability_key,
                    ok=False,
                    error_message="auth_user_id_required",
                )
            kwargs["auth_user_id"] = uuid.UUID(normalized_auth)
        if "data" in signature.parameters:
            kwargs["data"] = validated

        try:
            result = await handler(**kwargs)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "ACP capability execution failed "
                f"(capability={invocation.capability_key} "
                f"error={type(exc).__name__}: {exc})."
            )
            return CapabilityResult(
                capability_key=invocation.capability_key,
                ok=False,
                error_message=str(exc),
            )

        status_code = None
        payload = result
        if isinstance(result, tuple) and len(result) == 2:
            payload, status_code = result
        ok = status_code is None or int(status_code) < 400
        return CapabilityResult(
            capability_key=invocation.capability_key,
            ok=ok,
            result=payload,
            status_code=status_code,
        )

    def _descriptor_from_action(
        self,
        *,
        resource: Any,
        service: Any,
        action_name: str,
        schema: Any,
    ) -> CapabilityDescriptor | None:
        handler = getattr(service, f"action_{action_name}", None)
        if handler is None or not callable(handler):
            return None
        signature = inspect.signature(handler)
        requires_entity_id = "entity_id" in signature.parameters
        capability_key = f"{self._prefix}{resource.entity_set}__{action_name}"
        input_schema = (
            schema.model_json_schema()
            if hasattr(schema, "model_json_schema")
            else {"type": "object", "properties": {}, "additionalProperties": True}
        )
        if requires_entity_id:
            properties = dict(input_schema.get("properties") or {})
            properties["entity_id"] = {"type": "string", "format": "uuid"}
            input_schema = dict(input_schema)
            input_schema["properties"] = properties
            required = list(input_schema.get("required") or [])
            if "entity_id" not in required:
                required.append("entity_id")
            input_schema["required"] = required
        metadata = {
            "entity_set": resource.entity_set,
            "action_name": action_name,
            "schema": schema,
            "requires_entity_id": requires_entity_id,
            "requires_auth_user_id": "auth_user_id" in signature.parameters,
        }
        return CapabilityDescriptor(
            key=capability_key,
            title=f"{resource.entity_set}.{action_name}",
            description=f"ACP action {action_name} on {resource.entity_set}.",
            input_schema=input_schema,
            side_effect_class="write",
            metadata=metadata,
        )


class AllowlistExecutionGuard(IExecutionGuard):
    """Policy guard that enforces configured capability allowlists."""

    name = "allowlist_guard"

    async def validate(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        invocation: CapabilityInvocation,
        descriptor: CapabilityDescriptor,
        *,
        policy: AgentRuntimePolicy,
    ) -> None:
        _ = (request, run, descriptor)
        if policy.capability_allow and invocation.capability_key not in policy.capability_allow:
            raise RuntimeError(
                f"Capability {invocation.capability_key!r} is not allowed for this route."
            )


class TextResponseSynthesizer(IResponseSynthesizer):
    """Default text response synthesizer."""

    name = "text_default"

    async def synthesize(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        decision: PlanDecision,
        *,
        policy: AgentRuntimePolicy,
    ) -> list[dict]:
        _ = (request, run, policy)
        if decision.response_payloads:
            return [dict(item) for item in decision.response_payloads]
        response_text = decision.response_text
        if response_text is None and decision.completion is not None:
            response_text = _coerce_to_text(decision.completion.content)
        if _normalize_optional_text(response_text) is None:
            return []
        return [{"type": "text", "content": response_text}]


class RelationalPlanRunStore(IPlanRunStore):
    """Relational durable store for agent runs and append-only history."""

    _terminal_statuses = {
        PlanRunStatus.COMPLETED.value,
        PlanRunStatus.FAILED.value,
        PlanRunStatus.HANDOFF.value,
        PlanRunStatus.STOPPED.value,
    }

    def __init__(
        self,
        *,
        run_service: AgentPlanRunService,
        step_service: AgentPlanStepService,
    ) -> None:
        self._run_service = run_service
        self._step_service = step_service

    async def create_run(
        self,
        request: PlanRunRequest,
        *,
        state: PlanRunState,
        policy: AgentRuntimePolicy,
        lineage: PlanRunLineage | None = None,
        join_state: JoinState | None = None,
    ) -> PreparedPlanRun:
        tenant_id = uuid.UUID(request.scope.tenant_id)
        run_row = await self._run_service.create(
            {
                "tenant_id": tenant_id,
                "scope_key": _scope_key(request.scope),
                "mode": request.mode.value,
                "status": state.status.value,
                "service_route_key": request.service_route_key,
                "request_json": _request_snapshot(request),
                "policy_json": _serialize_policy(policy),
                "run_state_json": _serialize_state(state),
                "metadata_json": dict(request.metadata),
                "parent_run_id": _uuid_or_none(None if lineage is None else lineage.parent_run_id),
                "root_run_id": _uuid_or_none(None if lineage is None else lineage.root_run_id),
                "agent_key": _normalize_optional_text(
                    None
                    if lineage is None
                    else lineage.agent_key
                )
                or request.agent_key
                or policy.agent_key,
                "spawned_by_step_no": None if lineage is None else lineage.spawned_by_step_no,
                "join_state_json": _serialize_join_state(join_state),
                "current_sequence_no": 0,
                "next_wakeup_at": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "final_outcome_json": None,
                "last_error": None,
            }
        )
        if getattr(run_row, "root_run_id", None) is None:
            run_row = await self._run_service.update_with_row_version(
                {"id": run_row.id},
                expected_row_version=run_row.row_version,
                changes={"root_run_id": run_row.id},
            )
        return self._row_to_run(run_row)

    async def load_run(self, run_id: str) -> PreparedPlanRun | None:
        row = await self._get_run_row(run_id)
        if row is None:
            return None
        return self._row_to_run(row)

    async def save_run(self, run: PreparedPlanRun) -> PreparedPlanRun:
        run_uuid = uuid.UUID(run.run_id)
        updated = await self._run_service.update_with_row_version(
            {"id": run_uuid},
            expected_row_version=run.row_version,
            changes={
                "status": run.status.value,
                "service_route_key": run.service_route_key,
                "request_json": dict(run.request_snapshot),
                "policy_json": _serialize_policy(run.policy),
                "run_state_json": _serialize_state(run.state),
                "metadata_json": dict(run.metadata),
                "parent_run_id": _uuid_or_none(
                    None if run.lineage is None else run.lineage.parent_run_id
                ),
                "root_run_id": _uuid_or_none(
                    None if run.lineage is None else run.lineage.root_run_id
                ),
                "agent_key": _normalize_optional_text(
                    None if run.lineage is None else run.lineage.agent_key
                )
                or run.policy.agent_key,
                "spawned_by_step_no": None
                if run.lineage is None
                else run.lineage.spawned_by_step_no,
                "join_state_json": _serialize_join_state(run.join_state),
                "current_sequence_no": run.cursor.next_sequence_no - 1,
                "next_wakeup_at": run.next_wakeup_at,
                "lease_owner": None if run.lease is None else run.lease.owner,
                "lease_expires_at": None
                if run.lease is None
                else run.lease.expires_at,
                "final_outcome_json": _serialize_outcome(run.final_outcome),
                "last_error": run.state.last_error,
            },
        )
        return self._row_to_run(updated)

    async def append_step(
        self,
        *,
        run_id: str,
        step: PlanRunStep,
    ) -> PlanRunCursor:
        run_row = await self._require_run_row(run_id)
        await self._step_service.create(
            {
                "tenant_id": run_row.tenant_id,
                "run_id": run_row.id,
                "sequence_no": step.sequence_no,
                "step_kind": step.step_kind.value,
                "payload_json": dict(step.payload),
                "occurred_at": step.occurred_at or _utc_now(),
            }
        )
        updated = await self._run_service.update_with_row_version(
            {"id": run_row.id},
            expected_row_version=run_row.row_version,
            changes={"current_sequence_no": step.sequence_no},
        )
        return PlanRunCursor(
            run_id=str(updated.id),
            next_sequence_no=int(updated.current_sequence_no or 0) + 1,
            status=PlanRunStatus(str(updated.status)),
        )

    async def acquire_lease(
        self,
        *,
        run_id: str,
        owner: str,
        lease_seconds: int,
    ) -> PlanLease | None:
        row = await self._get_run_row(run_id)
        if row is None:
            return None
        now = _utc_now()
        if row.lease_expires_at is not None and row.lease_expires_at > now:
            if _normalize_optional_text(row.lease_owner) != _normalize_optional_text(owner):
                return None
        expires_at = now.replace(microsecond=0) + timedelta(seconds=lease_seconds)
        updated = await self._run_service.update_with_row_version(
            {"id": row.id},
            expected_row_version=row.row_version,
            changes={
                "lease_owner": owner,
                "lease_expires_at": expires_at,
            },
        )
        return PlanLease(owner=owner, expires_at=updated.lease_expires_at)

    async def release_lease(self, *, run_id: str, owner: str) -> None:
        row = await self._get_run_row(run_id)
        if row is None:
            return
        if _normalize_optional_text(row.lease_owner) != _normalize_optional_text(owner):
            return
        await self._run_service.update_with_row_version(
            {"id": row.id},
            expected_row_version=row.row_version,
            changes={"lease_owner": None, "lease_expires_at": None},
        )

    async def list_runnable_runs(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[PreparedPlanRun]:
        current = now or _utc_now()
        rows = await self._run_service.list(
            filter_groups=[FilterGroup(where={"mode": PlanRunMode.BACKGROUND.value})],
            order_by=[OrderBy(field="updated_at")],
            limit=max(limit * 4, limit),
        )
        due: list[PreparedPlanRun] = []
        for row in rows:
            if row.status in self._terminal_statuses:
                continue
            if row.lease_expires_at is not None and row.lease_expires_at > current:
                continue
            join_ready = await self._join_barrier_satisfied(row)
            if getattr(row, "join_state_json", None) is not None and join_ready is False:
                continue
            if join_ready:
                due.append(self._row_to_run(row))
                if len(due) >= limit:
                    break
                continue
            if row.next_wakeup_at is not None and row.next_wakeup_at > current:
                continue
            due.append(self._row_to_run(row))
            if len(due) >= limit:
                break
        return due

    async def finalize_run(
        self,
        *,
        run_id: str,
        outcome: PlanOutcome,
    ) -> PlanOutcome:
        row = await self._require_run_row(run_id)
        existing_outcome = _deserialize_outcome(row.final_outcome_json)
        if existing_outcome is not None:
            return existing_outcome
        updated = await self._run_service.update_with_row_version(
            {"id": row.id},
            expected_row_version=row.row_version,
            changes={
                "status": _outcome_status_to_run_status(outcome).value,
                "final_outcome_json": _serialize_outcome(outcome),
                "last_error": outcome.error_message,
                "next_wakeup_at": None,
                "lease_owner": None,
                "lease_expires_at": None,
            },
        )
        return _deserialize_outcome(updated.final_outcome_json) or outcome

    async def list_steps(self, *, run_id: str, limit: int | None = None) -> list[PlanRunStep]:
        run_row = await self._require_run_row(run_id)
        steps = await self._step_service.list(
            filter_groups=[FilterGroup(where={"tenant_id": run_row.tenant_id, "run_id": run_row.id})],
            order_by=[OrderBy(field="sequence_no")],
            limit=limit,
        )
        return [
            PlanRunStep(
                run_id=str(step.run_id),
                sequence_no=int(step.sequence_no or 0),
                step_kind=step.step_kind,
                payload=dict(step.payload_json or {}),
                occurred_at=step.occurred_at,
            )
            for step in steps
        ]

    async def list_child_runs(
        self,
        parent_run_id: str,
        *,
        terminal_only: bool = False,
    ) -> list[PreparedPlanRun]:
        parent_row = await self._require_run_row(parent_run_id)
        rows = await self._run_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": parent_row.tenant_id,
                        "parent_run_id": parent_row.id,
                    }
                )
            ],
            order_by=[OrderBy(field="created_at")],
        )
        runs = [self._row_to_run(row) for row in rows]
        if terminal_only:
            return [
                run
                for run in runs
                if run.status
                in {
                    PlanRunStatus.COMPLETED,
                    PlanRunStatus.FAILED,
                    PlanRunStatus.HANDOFF,
                    PlanRunStatus.STOPPED,
                }
            ]
        return runs

    async def load_run_graph(self, root_run_id: str) -> list[PreparedPlanRun]:
        root_row = await self._require_run_row(root_run_id)
        rows = await self._run_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": root_row.tenant_id,
                        "root_run_id": root_row.root_run_id or root_row.id,
                    }
                )
            ],
            order_by=[OrderBy(field="created_at")],
        )
        return [self._row_to_run(row) for row in rows]

    async def _get_run_row(self, run_id: str) -> AgentPlanRunDE | None:
        normalized = _normalize_optional_text(run_id)
        if normalized is None:
            return None
        return await self._run_service.get({"id": uuid.UUID(normalized)})

    async def _require_run_row(self, run_id: str) -> AgentPlanRunDE:
        row = await self._get_run_row(run_id)
        if row is None:
            raise RuntimeError(f"Unknown plan run: {run_id}.")
        return row

    async def _join_barrier_satisfied(self, row: AgentPlanRunDE) -> bool:
        join_state = _deserialize_join_state(getattr(row, "join_state_json", None))
        if join_state is None:
            return False
        if not join_state.required_child_run_ids:
            return True
        child_rows = await self._run_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": row.tenant_id,
                        "parent_run_id": row.id,
                    }
                )
            ],
            order_by=[OrderBy(field="created_at")],
        )
        terminal_ids = {
            str(child_row.id)
            for child_row in child_rows
            if child_row.status in self._terminal_statuses
        }
        return set(join_state.required_child_run_ids).issubset(terminal_ids)

    def _row_to_run(self, row: AgentPlanRunDE) -> PreparedPlanRun:
        run_id = str(row.id)
        status = PlanRunStatus(str(row.status or PlanRunStatus.PREPARED.value))
        policy = _deserialize_policy(row.policy_json)
        state = _deserialize_state(row.run_state_json)
        state.status = status
        lease = None
        if row.lease_owner is not None and row.lease_expires_at is not None:
            lease = PlanLease(owner=row.lease_owner, expires_at=row.lease_expires_at)
        lineage = None
        if (
            getattr(row, "parent_run_id", None) is not None
            or getattr(row, "root_run_id", None) is not None
            or _normalize_optional_text(getattr(row, "agent_key", None)) is not None
            or getattr(row, "spawned_by_step_no", None) is not None
        ):
            lineage = PlanRunLineage(
                parent_run_id=None
                if getattr(row, "parent_run_id", None) is None
                else str(row.parent_run_id),
                root_run_id=None
                if getattr(row, "root_run_id", None) is None
                else str(row.root_run_id),
                spawned_by_step_no=getattr(row, "spawned_by_step_no", None),
                agent_key=_normalize_optional_text(getattr(row, "agent_key", None)),
            )
        return PreparedPlanRun(
            run_id=run_id,
            mode=PlanRunMode(str(row.mode or PlanRunMode.CURRENT_TURN.value)),
            status=status,
            state=state,
            policy=policy,
            request_snapshot=dict(row.request_json or {}),
            cursor=PlanRunCursor(
                run_id=run_id,
                next_sequence_no=int(row.current_sequence_no or 0) + 1,
                status=status,
            ),
            service_route_key=_normalize_optional_text(row.service_route_key),
            lineage=lineage,
            join_state=_deserialize_join_state(getattr(row, "join_state_json", None)),
            next_wakeup_at=row.next_wakeup_at,
            lease=lease,
            final_outcome=_deserialize_outcome(row.final_outcome_json),
            created_at=row.created_at,
            updated_at=row.updated_at,
            row_version=row.row_version,
            metadata=dict(row.metadata_json or {}),
        )


class RelationalAgentScheduler(IAgentScheduler):
    """Scheduler facade backed by the relational run store."""

    def __init__(self, *, run_store: IPlanRunStore) -> None:
        self._run_store = run_store

    async def due_run_ids(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[str]:
        runs = await self._run_store.list_runnable_runs(limit=limit, now=now)
        return [run.run_id for run in runs]

    async def schedule_wait(
        self,
        *,
        run: PreparedPlanRun,
        wake_at: datetime | None,
    ) -> datetime | None:
        return wake_at


def _cfg_section(parent: Any, name: str) -> Any | None:
    if parent is None:
        return None
    if isinstance(parent, dict):
        value = parent.get(name)
    else:
        value = getattr(parent, name, None)
    if value in (None, ""):
        return None
    return value


def _cfg_value(parent: Any, name: str) -> Any:
    if isinstance(parent, dict):
        return parent.get(name)
    return getattr(parent, name, None)


def _cfg_list(parent: Any, name: str) -> list[Any]:
    value = _cfg_value(parent, name)
    if isinstance(value, list):
        return list(value)
    return []


def _outcome_status_to_run_status(outcome: PlanOutcome) -> PlanRunStatus:
    mapping = {
        PlanOutcomeStatus.COMPLETED: PlanRunStatus.COMPLETED,
        PlanOutcomeStatus.FAILED: PlanRunStatus.FAILED,
        PlanOutcomeStatus.HANDOFF: PlanRunStatus.HANDOFF,
        PlanOutcomeStatus.WAITING: PlanRunStatus.WAITING,
        PlanOutcomeStatus.SPAWNED_BACKGROUND: PlanRunStatus.COMPLETED,
        PlanOutcomeStatus.STOPPED: PlanRunStatus.STOPPED,
    }
    return mapping[outcome.status]
