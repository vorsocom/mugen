"""Default agent-runtime services and orchestration."""

from __future__ import annotations

__all__ = [
    "DefaultAgentExecutor",
    "DefaultAgentRuntime",
    "DefaultEvaluationEngine",
    "DefaultPlanRunStore",
    "DefaultPlanningEngine",
]

from dataclasses import fields
from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace
from typing import Any

from mugen.core import di
from mugen.core.contract.agent import (
    AgentRuntimePolicy,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityResult,
    DelegationArtifactRef,
    DelegationInstruction,
    EvaluationRequest,
    EvaluationResult,
    EvaluationStatus,
    IAgentExecutor,
    IAgentRuntime,
    IEvaluationEngine,
    IPlanRunStore,
    IPlanningEngine,
    JoinPolicy,
    JoinState,
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
    PlanRunStepKind,
    PreparedPlanRun,
)
from mugen.core.contract.context import ContextScope
from mugen.core.contract.gateway.completion import CompletionResponse
from mugen.core.contract.gateway.logging import ILoggingGateway

_EMPTY_AGENT_REGISTRY = SimpleNamespace(
    planners=[],
    evaluators=[],
    capability_providers=[],
    execution_guards=[],
    response_synthesizers=[],
    trace_sinks=[],
    policy_resolver=None,
    run_store=None,
    scheduler=None,
)


def _agent_component_registry_provider():
    return di.container.get_ext_service(
        di.EXT_SERVICE_AGENT_COMPONENT_REGISTRY,
        _EMPTY_AGENT_REGISTRY,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


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


def _serialize_capability_result(result: CapabilityResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "capability_key": result.capability_key,
        "ok": result.ok,
        "result": result.result,
        "status_code": result.status_code,
        "error_message": result.error_message,
        "metadata": dict(result.metadata),
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


def _serialize_artifact_ref(artifact: DelegationArtifactRef) -> dict[str, Any]:
    return {
        "artifact_key": artifact.artifact_key,
        "source_run_id": artifact.source_run_id,
        "source_step_sequence_no": artifact.source_step_sequence_no,
        "summary": artifact.summary,
        "payload": dict(artifact.payload),
        "metadata": dict(artifact.metadata),
    }


def _deserialize_artifact_ref(payload: dict[str, Any]) -> DelegationArtifactRef:
    return DelegationArtifactRef(
        artifact_key=str(payload.get("artifact_key") or ""),
        source_run_id=str(payload.get("source_run_id") or ""),
        source_step_sequence_no=payload.get("source_step_sequence_no"),
        summary=_normalize_optional_text(payload.get("summary")),
        payload=dict(payload.get("payload") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def _serialize_delegation_instruction(delegation: DelegationInstruction) -> dict[str, Any]:
    return {
        "agent_key": delegation.agent_key,
        "task_brief": delegation.task_brief,
        "service_route_key": delegation.service_route_key,
        "artifacts": [_serialize_artifact_ref(item) for item in delegation.artifacts],
        "required": delegation.required,
        "metadata": dict(delegation.metadata),
    }


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


def _lineage_from_request_metadata(metadata: dict[str, Any]) -> PlanRunLineage | None:
    payload = metadata.get("agent_lineage")
    if isinstance(payload, PlanRunLineage):
        return payload
    if isinstance(payload, dict):
        return _deserialize_lineage(payload)
    return None


def _join_state_from_request_metadata(metadata: dict[str, Any]) -> JoinState | None:
    payload = metadata.get("agent_join_state")
    if isinstance(payload, JoinState):
        return payload
    if isinstance(payload, dict):
        return _deserialize_join_state(payload)
    return None


def _serialize_observation(observation: PlanObservation) -> dict[str, Any]:
    return {
        "kind": observation.kind,
        "summary": observation.summary,
        "payload": dict(observation.payload),
        "success": observation.success,
        "capability_result": _serialize_capability_result(observation.capability_result),
        "completion": _serialize_completion(observation.completion),
        "metadata": dict(observation.metadata),
    }


def _serialize_decision(decision: PlanDecision) -> dict[str, Any]:
    return {
        "kind": decision.kind.value,
        "response_text": decision.response_text,
        "response_payloads": [dict(item) for item in decision.response_payloads],
        "capability_invocations": [
            {
                "capability_key": item.capability_key,
                "arguments": dict(item.arguments),
                "idempotency_key": item.idempotency_key,
                "metadata": dict(item.metadata),
            }
            for item in decision.capability_invocations
        ],
        "delegations": [
            _serialize_delegation_instruction(item) for item in decision.delegations
        ],
        "join_policy": _serialize_join_policy(decision.join_policy),
        "wait_until": None
        if decision.wait_until is None
        else decision.wait_until.isoformat(),
        "handoff_reason": decision.handoff_reason,
        "background_payload": (
            None if decision.background_payload is None else dict(decision.background_payload)
        ),
        "completion": _serialize_completion(decision.completion),
        "rationale_summary": decision.rationale_summary,
        "metadata": dict(decision.metadata),
    }


def _serialize_evaluation(result: EvaluationResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "reasons": list(result.reasons),
        "scores": dict(result.scores),
        "recommended_decision": (
            None
            if result.recommended_decision is None
            else result.recommended_decision.value
        ),
        "metadata": dict(result.metadata),
    }


def _serialize_outcome(outcome: PlanOutcome) -> dict[str, Any]:
    return {
        "status": outcome.status.value,
        "final_user_responses": [dict(item) for item in outcome.final_user_responses],
        "assistant_response": outcome.assistant_response,
        "completion": _serialize_completion(outcome.completion),
        "background_run_id": outcome.background_run_id,
        "error_message": outcome.error_message,
        "metadata": dict(outcome.metadata),
    }


def _first_text_response(responses: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str:
    for response in responses:
        if response.get("type") != "text":
            continue
        content = response.get("content")
        if isinstance(content, str):
            return content
    return ""


def _status_from_outcome(outcome: PlanOutcome) -> PlanRunStatus:
    mapping = {
        PlanOutcomeStatus.COMPLETED: PlanRunStatus.COMPLETED,
        PlanOutcomeStatus.FAILED: PlanRunStatus.FAILED,
        PlanOutcomeStatus.HANDOFF: PlanRunStatus.HANDOFF,
        PlanOutcomeStatus.WAITING: PlanRunStatus.WAITING,
        PlanOutcomeStatus.SPAWNED_BACKGROUND: PlanRunStatus.COMPLETED,
        PlanOutcomeStatus.STOPPED: PlanRunStatus.STOPPED,
    }
    return mapping[outcome.status]


def _outcome_status_from_run_status(status: PlanRunStatus) -> PlanOutcomeStatus:
    mapping = {
        PlanRunStatus.COMPLETED: PlanOutcomeStatus.COMPLETED,
        PlanRunStatus.FAILED: PlanOutcomeStatus.FAILED,
        PlanRunStatus.HANDOFF: PlanOutcomeStatus.HANDOFF,
        PlanRunStatus.WAITING: PlanOutcomeStatus.WAITING,
        PlanRunStatus.STOPPED: PlanOutcomeStatus.STOPPED,
        PlanRunStatus.PREPARED: PlanOutcomeStatus.FAILED,
        PlanRunStatus.ACTIVE: PlanOutcomeStatus.FAILED,
    }
    return mapping[status]


def _request_from_snapshot(snapshot: dict[str, Any], *, run_id: str) -> PlanRunRequest:
    scope_payload = dict(snapshot.get("scope") or {})
    scope = ContextScope(**scope_payload)
    return PlanRunRequest(
        mode=PlanRunMode(str(snapshot.get("mode") or PlanRunMode.BACKGROUND.value)),
        scope=scope,
        user_message=str(snapshot.get("user_message") or ""),
        message_id=_normalize_optional_text(snapshot.get("message_id")),
        trace_id=_normalize_optional_text(snapshot.get("trace_id")),
        service_route_key=_normalize_optional_text(snapshot.get("service_route_key")),
        agent_key=_normalize_optional_text(snapshot.get("agent_key")),
        ingress_metadata=dict(snapshot.get("ingress_metadata") or {}),
        run_id=run_id,
        metadata=dict(snapshot.get("metadata") or {}),
    )


class _AgentServiceBase:
    def __init__(self, config: SimpleNamespace, logging_gateway: ILoggingGateway) -> None:
        self._config = config
        self._logging_gateway = logging_gateway

    @staticmethod
    def _registry():
        return _agent_component_registry_provider()

    def _resolve_policy_resolver(self):
        return getattr(self._registry(), "policy_resolver", None)

    async def _resolve_policy(self, request: PlanRunRequest) -> AgentRuntimePolicy:
        resolver = self._resolve_policy_resolver()
        if resolver is None:
            return AgentRuntimePolicy()
        return await resolver.resolve_policy(request)

    def _require_run_store(self) -> IPlanRunStore:
        run_store = getattr(self._registry(), "run_store", None)
        if run_store is None:
            raise RuntimeError("Agent runtime run store is not registered.")
        return run_store


class DefaultPlanningEngine(_AgentServiceBase, IPlanningEngine):
    """Select a planner strategy and manage durable run handles."""

    async def prepare_run(self, request: PlanRunRequest) -> PreparedPlanRun:
        if not isinstance(request, PlanRunRequest):
            raise TypeError("DefaultPlanningEngine requires PlanRunRequest.")

        policy = await self._resolve_policy(request)
        resolved_route_key = _normalize_optional_text(policy.metadata.get("service_route_key"))
        if request.service_route_key is None and resolved_route_key is not None:
            request.service_route_key = resolved_route_key
        if request.agent_key is None and policy.agent_key is not None:
            request.agent_key = policy.agent_key
        missing_agent_key = _normalize_optional_text(policy.metadata.get("agent_definition_missing"))
        if missing_agent_key is not None:
            raise RuntimeError(f"Unknown agent definition: {missing_agent_key}.")
        run_store = self._require_run_store()

        if request.run_id is not None:
            existing = await run_store.load_run(request.run_id)
            if existing is None:
                raise RuntimeError(f"Unknown plan run: {request.run_id}.")
            existing.policy = policy
            existing.service_route_key = request.service_route_key
            existing.request_snapshot["service_route_key"] = request.service_route_key
            existing.request_snapshot["agent_key"] = request.agent_key
            if request.agent_key is not None and existing.lineage is not None:
                existing.lineage.agent_key = request.agent_key
            return await run_store.save_run(existing)

        initial_status = (
            PlanRunStatus.ACTIVE
            if request.mode == PlanRunMode.CURRENT_TURN
            else PlanRunStatus.PREPARED
        )
        state = PlanRunState(goal=request.user_message, status=initial_status)
        created = await run_store.create_run(
            request,
            state=state,
            policy=policy,
            lineage=_lineage_from_request_metadata(request.metadata),
            join_state=_join_state_from_request_metadata(request.metadata),
        )
        created.status = initial_status
        created.state.status = initial_status
        created.service_route_key = request.service_route_key
        created.request_snapshot["service_route_key"] = request.service_route_key
        created.request_snapshot["agent_key"] = request.agent_key
        return await run_store.save_run(created)

    async def next_decision(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        observations: tuple,
    ) -> PlanDecision:
        planner = self._select_planner(run.policy)
        return await planner.next_decision(
            request,
            run,
            tuple(observations or ()),
            policy=run.policy,
        )

    async def finalize_run(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        outcome: PlanOutcome,
    ) -> PreparedPlanRun:
        try:
            planner = self._select_planner(run.policy)
            await planner.finalize_run(request, run, outcome, policy=run.policy)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Agent planner finalization failed "
                f"(run_id={run.run_id} error={type(exc).__name__}: {exc})."
            )
        run.status = _status_from_outcome(outcome)
        run.state.status = run.status
        run.state.last_response_text = outcome.assistant_response
        run.state.last_error = outcome.error_message
        run.final_outcome = outcome
        return await self._require_run_store().save_run(run)

    def _select_planner(self, policy: AgentRuntimePolicy):
        planners = list(getattr(self._registry(), "planners", []) or [])
        if not planners:
            raise RuntimeError("Agent runtime planner strategy is not registered.")
        preferred = _normalize_optional_text(policy.planner_key)
        if preferred is not None:
            for planner in planners:
                if _normalize_optional_text(getattr(planner, "name", None)) == preferred:
                    return planner
        return planners[0]


class DefaultEvaluationEngine(_AgentServiceBase, IEvaluationEngine):
    """Select an evaluator strategy and apply deterministic fallbacks."""

    async def evaluate_step(self, request: EvaluationRequest) -> EvaluationResult:
        evaluator = self._select_evaluator(request.run.policy)
        if evaluator is None:
            for observation in request.observations:
                result = observation.capability_result
                if result is not None and result.ok is False:
                    return EvaluationResult(
                        status=EvaluationStatus.REPLAN,
                        reasons=(result.error_message or "capability_failed",),
                    )
            return EvaluationResult(status=EvaluationStatus.PASS)
        return await evaluator.evaluate_step(request, policy=request.run.policy)

    async def evaluate_response(self, request: EvaluationRequest) -> EvaluationResult:
        evaluator = self._select_evaluator(request.run.policy)
        if evaluator is None:
            if _normalize_optional_text(request.draft_response_text) is None:
                return EvaluationResult(
                    status=EvaluationStatus.RETRY,
                    reasons=("blank_response",),
                )
            return EvaluationResult(status=EvaluationStatus.PASS)
        return await evaluator.evaluate_response(request, policy=request.run.policy)

    async def evaluate_run(
        self,
        request: EvaluationRequest,
        outcome: PlanOutcome,
    ) -> EvaluationResult:
        evaluator = self._select_evaluator(request.run.policy)
        if evaluator is None:
            if outcome.status == PlanOutcomeStatus.FAILED:
                return EvaluationResult(
                    status=EvaluationStatus.ESCALATE,
                    reasons=(outcome.error_message or "run_failed",),
                )
            return EvaluationResult(status=EvaluationStatus.PASS)
        return await evaluator.evaluate_run(request, outcome, policy=request.run.policy)

    def _select_evaluator(self, policy: AgentRuntimePolicy):
        evaluators = list(getattr(self._registry(), "evaluators", []) or [])
        if not evaluators:
            return None
        preferred = _normalize_optional_text(policy.evaluator_key)
        if preferred is not None:
            for evaluator in evaluators:
                if _normalize_optional_text(getattr(evaluator, "name", None)) == preferred:
                    return evaluator
        return evaluators[0]


class DefaultAgentExecutor(_AgentServiceBase, IAgentExecutor):
    """Composite capability catalog and executor facade."""

    async def list_capabilities(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
    ) -> list[CapabilityDescriptor]:
        seen: dict[str, CapabilityDescriptor] = {}
        allowed = set(run.policy.capability_allow)
        for provider in list(getattr(self._registry(), "capability_providers", []) or []):
            descriptors = await provider.list_capabilities(
                request,
                run,
                policy=run.policy,
            )
            for descriptor in descriptors:
                if allowed and descriptor.key not in allowed:
                    continue
                seen.setdefault(descriptor.key, descriptor)
        return list(seen.values())

    async def execute_capability(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        invocation: CapabilityInvocation,
    ) -> CapabilityResult:
        descriptors = {
            item.key: item for item in await self.list_capabilities(request, run)
        }
        descriptor = descriptors.get(invocation.capability_key)
        if descriptor is None:
            return CapabilityResult(
                capability_key=invocation.capability_key,
                ok=False,
                error_message="unknown_capability",
            )

        for guard in list(getattr(self._registry(), "execution_guards", []) or []):
            await guard.validate(
                request,
                run,
                invocation,
                descriptor,
                policy=run.policy,
            )

        for provider in list(getattr(self._registry(), "capability_providers", []) or []):
            if provider.supports(invocation.capability_key):
                try:
                    return await provider.execute(
                        request,
                        run,
                        invocation,
                        descriptor,
                        policy=run.policy,
                    )
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    self._logging_gateway.warning(
                        "Agent capability execution failed "
                        f"(capability={invocation.capability_key} "
                        f"error={type(exc).__name__}: {exc})."
                    )
                    return CapabilityResult(
                        capability_key=invocation.capability_key,
                        ok=False,
                        error_message=str(exc),
                    )

        return CapabilityResult(
            capability_key=invocation.capability_key,
            ok=False,
            error_message="unsupported_capability",
        )


class DefaultPlanRunStore(_AgentServiceBase, IPlanRunStore):
    """First-class run-store provider backed by the plugin-owned store."""

    async def create_run(
        self,
        request: PlanRunRequest,
        *,
        state: PlanRunState,
        policy: AgentRuntimePolicy,
        lineage: PlanRunLineage | None = None,
        join_state: JoinState | None = None,
    ) -> PreparedPlanRun:
        return await self._require_run_store().create_run(
            request,
            state=state,
            policy=policy,
            lineage=lineage,
            join_state=join_state,
        )

    async def load_run(self, run_id: str) -> PreparedPlanRun | None:
        return await self._require_run_store().load_run(run_id)

    async def save_run(self, run: PreparedPlanRun) -> PreparedPlanRun:
        return await self._require_run_store().save_run(run)

    async def append_step(
        self,
        *,
        run_id: str,
        step: PlanRunStep,
    ) -> PlanRunCursor:
        return await self._require_run_store().append_step(run_id=run_id, step=step)

    async def acquire_lease(
        self,
        *,
        run_id: str,
        owner: str,
        lease_seconds: int,
    ) -> PlanLease | None:
        return await self._require_run_store().acquire_lease(
            run_id=run_id,
            owner=owner,
            lease_seconds=lease_seconds,
        )

    async def release_lease(self, *, run_id: str, owner: str) -> None:
        await self._require_run_store().release_lease(run_id=run_id, owner=owner)

    async def list_runnable_runs(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[PreparedPlanRun]:
        return await self._require_run_store().list_runnable_runs(limit=limit, now=now)

    async def finalize_run(
        self,
        *,
        run_id: str,
        outcome: PlanOutcome,
    ) -> PlanOutcome:
        return await self._require_run_store().finalize_run(run_id=run_id, outcome=outcome)

    async def list_steps(self, *, run_id: str, limit: int | None = None) -> list[PlanRunStep]:
        return await self._require_run_store().list_steps(run_id=run_id, limit=limit)

    async def list_child_runs(
        self,
        parent_run_id: str,
        *,
        terminal_only: bool = False,
    ) -> list[PreparedPlanRun]:
        return await self._require_run_store().list_child_runs(
            parent_run_id,
            terminal_only=terminal_only,
        )

    async def load_run_graph(self, root_run_id: str) -> list[PreparedPlanRun]:
        return await self._require_run_store().load_run_graph(root_run_id)


class DefaultAgentRuntime(_AgentServiceBase, IAgentRuntime):
    """Current-turn and background orchestration above the agent-runtime seams."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
        planning_engine_service: IPlanningEngine | None = None,
        evaluation_engine_service: IEvaluationEngine | None = None,
        agent_executor_service: IAgentExecutor | None = None,
        plan_run_store_service: IPlanRunStore | None = None,
    ) -> None:
        super().__init__(config=config, logging_gateway=logging_gateway)
        self._planning_engine_service = planning_engine_service
        self._evaluation_engine_service = evaluation_engine_service
        self._agent_executor_service = agent_executor_service
        self._plan_run_store_service = plan_run_store_service

    async def is_enabled_for_request(self, request: PlanRunRequest) -> bool:
        policy = await self._resolve_policy(request)
        if not policy.enabled:
            return False
        if request.mode == PlanRunMode.CURRENT_TURN:
            return policy.current_turn_enabled
        return policy.background_enabled

    async def run_current_turn(self, request: PlanRunRequest) -> PlanOutcome:
        if request.mode != PlanRunMode.CURRENT_TURN:
            raise ValueError("run_current_turn requires current_turn mode.")
        if request.prepared_context is None:
            raise ValueError("run_current_turn requires prepared_context.")
        if self._planning_engine_service is None:
            raise RuntimeError("planning_engine_service is not configured.")
        if self._evaluation_engine_service is None:
            raise RuntimeError("evaluation_engine_service is not configured.")
        if self._agent_executor_service is None:
            raise RuntimeError("agent_executor_service is not configured.")
        if self._plan_run_store_service is None:
            raise RuntimeError("plan_run_store_service is not configured.")

        run = await self._planning_engine_service.prepare_run(request)
        request.run_id = run.run_id
        request.available_capabilities = tuple(
            await self._agent_executor_service.list_capabilities(request, run)
        )
        return await self._run_loop(
            request=request,
            run=run,
            max_iterations=max(1, int(run.policy.max_iterations)),
            allow_wait=False,
        )

    async def run_background_batch(
        self,
        *,
        owner: str,
        limit: int = 20,
        now: datetime | None = None,
    ) -> list[PlanOutcome]:
        if self._planning_engine_service is None:
            raise RuntimeError("planning_engine_service is not configured.")
        if self._evaluation_engine_service is None:
            raise RuntimeError("evaluation_engine_service is not configured.")
        if self._agent_executor_service is None:
            raise RuntimeError("agent_executor_service is not configured.")
        if self._plan_run_store_service is None:
            raise RuntimeError("plan_run_store_service is not configured.")

        normalized_owner = _normalize_optional_text(owner)
        if normalized_owner is None:
            raise ValueError("Background owner is required.")
        due_runs = await self._list_due_runs(limit=limit, now=now)
        outcomes: list[PlanOutcome] = []
        for due_run in due_runs:
            lease = await self._plan_run_store_service.acquire_lease(
                run_id=due_run.run_id,
                owner=normalized_owner,
                lease_seconds=max(1, int(due_run.policy.lease_seconds)),
            )
            if lease is None:
                continue
            due_run.lease = lease
            try:
                due_run = await self._reload_run_handle(
                    due_run,
                    operation="lease acquisition",
                )
            except RuntimeError:
                await self._plan_run_store_service.release_lease(
                    run_id=due_run.run_id,
                    owner=normalized_owner,
                )
                raise
            request = _request_from_snapshot(due_run.request_snapshot, run_id=due_run.run_id)
            request.mode = PlanRunMode.BACKGROUND
            request.available_capabilities = tuple(
                await self._agent_executor_service.list_capabilities(request, due_run)
            )
            try:
                outcome = await self._run_loop(
                    request=request,
                    run=due_run,
                    max_iterations=max(1, int(due_run.policy.max_background_iterations)),
                    allow_wait=True,
                )
            finally:
                await self._plan_run_store_service.release_lease(
                    run_id=due_run.run_id,
                    owner=normalized_owner,
                )
            outcomes.append(outcome)
        return outcomes

    async def _run_loop(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        max_iterations: int,
        allow_wait: bool,
    ) -> PlanOutcome:
        observations, pending_outcome, finalize_pending = await self._bootstrap_observations(
            request=request,
            run=run,
        )
        if pending_outcome is not None and finalize_pending is False:
            return pending_outcome

        run.status = PlanRunStatus.ACTIVE
        run.state.status = PlanRunStatus.ACTIVE
        run = await self._plan_run_store_service.save_run(run)
        for observation in observations:
            run = await self._append_step(
                request=request,
                run=run,
                step_kind=PlanRunStepKind.OBSERVATION,
                payload=_serialize_observation(observation),
            )
        if pending_outcome is not None:
            return await self._finalize_terminal(
                request=request,
                run=run,
                outcome=pending_outcome,
            )

        for iteration in range(max_iterations):
            run.state.iteration_count = iteration + 1
            if request.mode == PlanRunMode.BACKGROUND:
                run.state.background_iteration_count = iteration + 1
            decision = await self._planning_engine_service.next_decision(
                request,
                run,
                observations,
            )
            run = await self._append_step(
                request=request,
                run=run,
                step_kind=PlanRunStepKind.DECISION,
                payload=_serialize_decision(decision),
            )

            if decision.kind == PlanDecisionKind.EXECUTE_ACTION:
                observations = await self._execute_decision(
                    request=request,
                    run=run,
                    decision=decision,
                )
                evaluation = await self._evaluation_engine_service.evaluate_step(
                    EvaluationRequest(
                        request=request,
                        run=run,
                        decision=decision,
                        observations=observations,
                    )
                )
                run = await self._append_step(
                    request=request,
                    run=run,
                    step_kind=PlanRunStepKind.EVALUATION,
                    payload=_serialize_evaluation(evaluation),
                )
                if evaluation.status == EvaluationStatus.PASS:
                    continue
                if evaluation.status in {
                    EvaluationStatus.RETRY,
                    EvaluationStatus.REPLAN,
                }:
                    observations = observations + (
                        PlanObservation(
                            kind="evaluation",
                            summary="planner_retry",
                            payload=_serialize_evaluation(evaluation),
                            metadata={"evaluation_status": evaluation.status.value},
                        ),
                    )
                    continue
                return await self._finalize_terminal(
                    request=request,
                    run=run,
                    outcome=PlanOutcome(
                        status=PlanOutcomeStatus.HANDOFF
                        if evaluation.status == EvaluationStatus.ESCALATE
                        else PlanOutcomeStatus.FAILED,
                        error_message="step_evaluation_blocked",
                        metadata={"evaluation": _serialize_evaluation(evaluation)},
                    ),
                )

            if decision.kind == PlanDecisionKind.RESPOND:
                responses = await self._synthesize_response(
                    request=request,
                    run=run,
                    decision=decision,
                )
                assistant_response = _first_text_response(responses) or (
                    decision.response_text or ""
                )
                evaluation = await self._evaluation_engine_service.evaluate_response(
                    EvaluationRequest(
                        request=request,
                        run=run,
                        decision=decision,
                        observations=observations,
                        draft_response_text=assistant_response,
                        final_user_responses=tuple(responses),
                    )
                )
                run = await self._append_step(
                    request=request,
                    run=run,
                    step_kind=PlanRunStepKind.EVALUATION,
                    payload=_serialize_evaluation(evaluation),
                )
                if evaluation.status == EvaluationStatus.PASS:
                    return await self._finalize_terminal(
                        request=request,
                        run=run,
                        outcome=PlanOutcome(
                            status=PlanOutcomeStatus.COMPLETED,
                            final_user_responses=tuple(responses),
                            assistant_response=assistant_response,
                            completion=decision.completion,
                        ),
                    )
                if evaluation.status in {
                    EvaluationStatus.RETRY,
                    EvaluationStatus.REPLAN,
                }:
                    observations = observations + (
                        PlanObservation(
                            kind="response_evaluation",
                            summary="retry_response",
                            payload={
                                "assistant_response": assistant_response,
                                "evaluation": _serialize_evaluation(evaluation),
                            },
                            completion=decision.completion,
                        ),
                    )
                    continue
                return await self._finalize_terminal(
                    request=request,
                    run=run,
                    outcome=PlanOutcome(
                        status=PlanOutcomeStatus.HANDOFF
                        if evaluation.status == EvaluationStatus.ESCALATE
                        else PlanOutcomeStatus.FAILED,
                        assistant_response=assistant_response,
                        completion=decision.completion,
                        error_message="response_evaluation_blocked",
                        metadata={"evaluation": _serialize_evaluation(evaluation)},
                    ),
                )

            if decision.kind == PlanDecisionKind.SPAWN_BACKGROUND:
                background_run_id = await self._spawn_background_run(
                    request=request,
                    run=run,
                    decision=decision,
                )
                responses = await self._synthesize_response(
                    request=request,
                    run=run,
                    decision=decision,
                )
                assistant_response = _first_text_response(responses) or (
                    decision.response_text or ""
                )
                return await self._finalize_terminal(
                    request=request,
                    run=run,
                    outcome=PlanOutcome(
                        status=PlanOutcomeStatus.SPAWNED_BACKGROUND,
                        final_user_responses=tuple(responses),
                        assistant_response=assistant_response,
                        completion=decision.completion,
                        background_run_id=background_run_id,
                    ),
                )

            if decision.kind == PlanDecisionKind.DELEGATE:
                if allow_wait is not True or request.mode != PlanRunMode.BACKGROUND:
                    return await self._finalize_terminal(
                        request=request,
                        run=run,
                        outcome=PlanOutcome(
                            status=PlanOutcomeStatus.HANDOFF,
                            error_message="delegate_not_allowed_in_current_turn",
                        ),
                    )
                try:
                    return await self._delegate_to_children(
                        request=request,
                        run=run,
                        decision=decision,
                    )
                except RuntimeError as exc:
                    return await self._finalize_terminal(
                        request=request,
                        run=run,
                        outcome=PlanOutcome(
                            status=PlanOutcomeStatus.HANDOFF,
                            error_message=str(exc),
                        ),
                    )

            if decision.kind == PlanDecisionKind.WAIT:
                if allow_wait is not True:
                    return await self._finalize_terminal(
                        request=request,
                        run=run,
                        outcome=PlanOutcome(
                            status=PlanOutcomeStatus.HANDOFF,
                            error_message="wait_not_allowed_in_current_turn",
                        ),
                    )
                return await self._mark_waiting(
                    request=request,
                    run=run,
                    decision=decision,
                )

            if decision.kind == PlanDecisionKind.HANDOFF:
                responses = await self._synthesize_response(
                    request=request,
                    run=run,
                    decision=decision,
                )
                return await self._finalize_terminal(
                    request=request,
                    run=run,
                    outcome=PlanOutcome(
                        status=PlanOutcomeStatus.HANDOFF,
                        final_user_responses=tuple(responses),
                        assistant_response=_first_text_response(responses)
                        or decision.response_text,
                        completion=decision.completion,
                        error_message=decision.handoff_reason,
                    ),
                )

            return await self._finalize_terminal(
                request=request,
                run=run,
                outcome=PlanOutcome(
                    status=PlanOutcomeStatus.STOPPED,
                    assistant_response=decision.response_text,
                    completion=decision.completion,
                    error_message=decision.handoff_reason,
                ),
            )

        return await self._finalize_terminal(
            request=request,
            run=run,
            outcome=PlanOutcome(
                status=PlanOutcomeStatus.FAILED,
                error_message="max_iterations_exceeded",
            ),
        )

    async def _bootstrap_observations(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
    ) -> tuple[tuple[PlanObservation, ...], PlanOutcome | None, bool]:
        observations = tuple(await self._initial_request_observations(request=request, run=run))
        if request.mode != PlanRunMode.BACKGROUND or run.join_state is None:
            return observations, None, False

        join_observations, join_outcome, finalize_pending = await self._resume_join_state(
            request=request,
            run=run,
        )
        return observations + join_observations, join_outcome, finalize_pending

    async def _initial_request_observations(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
    ) -> list[PlanObservation]:
        if int(run.state.iteration_count or 0) > 0:
            return []
        delegation_payload = request.metadata.get("delegation")
        if not isinstance(delegation_payload, dict):
            return []
        observations = [
            PlanObservation(
                kind="delegation_brief",
                summary=_normalize_optional_text(delegation_payload.get("task_brief"))
                or "delegated_task",
                payload={
                    "parent_run_id": _normalize_optional_text(
                        delegation_payload.get("parent_run_id")
                    ),
                    "parent_agent_key": _normalize_optional_text(
                        delegation_payload.get("parent_agent_key")
                    ),
                    "delegated_agent_key": _normalize_optional_text(
                        delegation_payload.get("delegated_agent_key")
                    ),
                    "task_brief": _normalize_optional_text(
                        delegation_payload.get("task_brief")
                    ),
                    "required": bool(delegation_payload.get("required", True)),
                },
                metadata=dict(delegation_payload.get("metadata") or {}),
            )
        ]
        for artifact_payload in delegation_payload.get("artifacts") or ():
            if not isinstance(artifact_payload, dict):
                continue
            artifact = _deserialize_artifact_ref(artifact_payload)
            observations.append(
                PlanObservation(
                    kind="delegation_artifact",
                    summary=artifact.summary or artifact.artifact_key,
                    payload=_serialize_artifact_ref(artifact),
                    metadata=dict(artifact.metadata),
                )
            )
        return observations

    async def _resume_join_state(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
    ) -> tuple[tuple[PlanObservation, ...], PlanOutcome | None, bool]:
        join_state = run.join_state
        if join_state is None:
            return (), None, False

        child_runs = await self._plan_run_store_service.list_child_runs(run.run_id)
        child_by_id = {child.run_id: child for child in child_runs}
        required_ids = set(join_state.required_child_run_ids)
        terminal_children: dict[str, PreparedPlanRun] = {}
        for child_run_id, child_run in child_by_id.items():
            if child_run.status in {
                PlanRunStatus.COMPLETED,
                PlanRunStatus.FAILED,
                PlanRunStatus.HANDOFF,
                PlanRunStatus.STOPPED,
            }:
                terminal_children[child_run_id] = child_run

        completed_ids = set(join_state.completed_child_run_ids) | set(terminal_children)
        timeout_outcome = self._join_timeout_outcome(
            join_state=join_state,
            completed_ids=completed_ids,
        )
        if timeout_outcome is not None:
            run.join_state = None
            run.next_wakeup_at = None
            return (), timeout_outcome, True
        if required_ids - completed_ids:
            run.join_state.completed_child_run_ids = tuple(sorted(completed_ids))
            run.status = PlanRunStatus.WAITING
            run.state.status = PlanRunStatus.WAITING
            run.next_wakeup_at = None
            run = await self._plan_run_store_service.save_run(run)
            outcome = PlanOutcome(
                status=PlanOutcomeStatus.WAITING,
                metadata={
                    "run_id": run.run_id,
                    "waiting_on_child_run_ids": sorted(required_ids - completed_ids),
                },
            )
            await self._record_outcome(request=request, run=run, outcome=outcome)
            return (), outcome, False

        observations = tuple(
            self._child_run_observation(child_run)
            for child_run_id, child_run in child_by_id.items()
            if child_run_id in completed_ids
        )
        terminal_outcome = self._terminal_outcome_from_join_state(
            join_state=join_state,
            child_runs=child_by_id,
        )
        run.join_state = None
        run.next_wakeup_at = None
        return observations, terminal_outcome, terminal_outcome is not None

    def _child_run_observation(self, child_run: PreparedPlanRun) -> PlanObservation:
        outcome = child_run.final_outcome
        return PlanObservation(
            kind="child_run_result",
            summary=outcome.assistant_response if outcome is not None else child_run.status.value,
            payload={
                "child_run_id": child_run.run_id,
                "agent_key": None if child_run.lineage is None else child_run.lineage.agent_key,
                "status": child_run.status.value,
                "assistant_response": None if outcome is None else outcome.assistant_response,
                "error_message": None if outcome is None else outcome.error_message,
                "metadata": {} if outcome is None else dict(outcome.metadata),
            },
            success=child_run.status == PlanRunStatus.COMPLETED,
            metadata={
                "lineage": _serialize_lineage(child_run.lineage),
                "final_outcome": None if outcome is None else _serialize_outcome(outcome),
            },
        )

    def _terminal_outcome_from_join_state(
        self,
        *,
        join_state: JoinState,
        child_runs: dict[str, PreparedPlanRun],
    ) -> PlanOutcome | None:
        required_ids = set(join_state.required_child_run_ids)
        for child_run_id in required_ids:
            child_run = child_runs.get(child_run_id)
            if child_run is None:
                continue
            if child_run.status == PlanRunStatus.FAILED:
                return PlanOutcome(
                    status=join_state.policy.on_required_child_failed,
                    error_message="required_child_failed",
                    metadata={"child_run_id": child_run_id},
                )
            if child_run.status == PlanRunStatus.HANDOFF:
                return PlanOutcome(
                    status=join_state.policy.on_required_child_handoff,
                    error_message="required_child_handoff",
                    metadata={"child_run_id": child_run_id},
                )
            if child_run.status == PlanRunStatus.STOPPED:
                return PlanOutcome(
                    status=join_state.policy.on_required_child_stopped,
                    error_message="required_child_stopped",
                    metadata={"child_run_id": child_run_id},
                )
        return None

    async def _delegate_to_children(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        decision: PlanDecision,
    ) -> PlanOutcome:
        if not decision.delegations:
            raise RuntimeError("delegate_requires_child_instructions")
        allowed_agents = set(run.policy.delegate_agent_allow)
        decision_sequence_no = run.cursor.next_sequence_no - 1
        root_run_id = (
            run.run_id
            if run.lineage is None or run.lineage.root_run_id is None
            else run.lineage.root_run_id
        )
        child_run_ids: list[str] = []
        required_child_run_ids: list[str] = []
        child_run_summaries: list[dict[str, Any]] = []
        for delegation in decision.delegations:
            if allowed_agents and delegation.agent_key not in allowed_agents:
                raise RuntimeError(f"delegate_agent_not_allowed:{delegation.agent_key}")
            child_request = PlanRunRequest(
                mode=PlanRunMode.BACKGROUND,
                scope=request.scope,
                user_message=delegation.task_brief,
                message_id=request.message_id,
                trace_id=request.trace_id,
                service_route_key=delegation.service_route_key,
                agent_key=delegation.agent_key,
                ingress_metadata=dict(request.ingress_metadata),
                metadata=self._child_request_metadata(
                    request=request,
                    run=run,
                    delegation=delegation,
                    root_run_id=root_run_id,
                    decision_sequence_no=decision_sequence_no,
                ),
            )
            child_run = await self._planning_engine_service.prepare_run(child_request)
            child_run_ids.append(child_run.run_id)
            if delegation.required:
                required_child_run_ids.append(child_run.run_id)
            child_run_summaries.append(
                {
                    "child_run_id": child_run.run_id,
                    "agent_key": delegation.agent_key,
                    "service_route_key": child_run.service_route_key,
                    "required": delegation.required,
                }
            )

        run.join_state = JoinState(
            child_run_ids=tuple(child_run_ids),
            required_child_run_ids=tuple(required_child_run_ids),
            completed_child_run_ids=(),
            last_joined_sequence_no=decision_sequence_no,
            timeout_at=self._join_timeout_at(decision.join_policy),
            policy=decision.join_policy or JoinPolicy(),
            metadata={
                "delegations": [
                    _serialize_delegation_instruction(item) for item in decision.delegations
                ],
            },
        )
        run.status = PlanRunStatus.WAITING
        run.state.status = PlanRunStatus.WAITING
        run.next_wakeup_at = None
        run = await self._plan_run_store_service.save_run(run)
        run = await self._append_step(
            request=request,
            run=run,
            step_kind=PlanRunStepKind.EFFECT,
            payload={
                "kind": "delegate",
                "child_runs": child_run_summaries,
                "join_state": _serialize_join_state(run.join_state),
            },
        )
        outcome = PlanOutcome(
            status=PlanOutcomeStatus.WAITING,
            metadata={
                "run_id": run.run_id,
                "child_run_ids": child_run_ids,
            },
        )
        await self._record_outcome(request=request, run=run, outcome=outcome)
        return outcome

    def _join_timeout_outcome(
        self,
        *,
        join_state: JoinState,
        completed_ids: set[str],
    ) -> PlanOutcome | None:
        timeout_at = join_state.timeout_at
        if timeout_at is None or timeout_at > _utc_now():
            return None
        pending_ids = sorted(
            set(join_state.required_child_run_ids) - set(completed_ids)
        )
        return PlanOutcome(
            status=join_state.policy.on_required_child_failed,
            error_message="join_timeout_elapsed",
            metadata={
                "timed_out_at": timeout_at.isoformat(),
                "waiting_on_child_run_ids": pending_ids,
            },
        )

    def _join_timeout_at(self, join_policy: JoinPolicy | None) -> datetime | None:
        if join_policy is None:
            return None
        metadata = dict(join_policy.metadata or {})
        timeout_at = metadata.get("timeout_at")
        if isinstance(timeout_at, datetime):
            return timeout_at
        if isinstance(timeout_at, str) and timeout_at.strip() != "":
            return datetime.fromisoformat(timeout_at)
        timeout_seconds = metadata.get("timeout_seconds")
        if isinstance(timeout_seconds, bool):
            return None
        if isinstance(timeout_seconds, (int, float)) and timeout_seconds > 0:
            return _utc_now() + timedelta(seconds=float(timeout_seconds))
        return None

    def _child_request_metadata(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        delegation: DelegationInstruction,
        root_run_id: str,
        decision_sequence_no: int,
    ) -> dict[str, Any]:
        reserved_keys = {
            "agent_lineage",
            "agent_join_state",
            "delegation",
            "background_payload",
            "spawned_from_run_id",
        }
        base_metadata = {
            key: value for key, value in dict(request.metadata).items() if key not in reserved_keys
        }
        lineage = PlanRunLineage(
            parent_run_id=run.run_id,
            root_run_id=root_run_id,
            spawned_by_step_no=decision_sequence_no,
            agent_key=delegation.agent_key,
        )
        base_metadata["agent_lineage"] = _serialize_lineage(lineage)
        base_metadata["delegation"] = {
            "parent_run_id": run.run_id,
            "parent_agent_key": run.policy.agent_key,
            "delegated_agent_key": delegation.agent_key,
            "task_brief": delegation.task_brief,
            "required": delegation.required,
            "artifacts": [
                _serialize_artifact_ref(item) for item in delegation.artifacts
            ],
            "metadata": dict(delegation.metadata),
        }
        return base_metadata

    async def _execute_decision(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        decision: PlanDecision,
    ) -> tuple[PlanObservation, ...]:
        observations: list[PlanObservation] = []
        for invocation in decision.capability_invocations:
            result = await self._agent_executor_service.execute_capability(
                request,
                run,
                invocation,
            )
            observation = PlanObservation(
                kind="capability_result",
                summary=result.error_message or invocation.capability_key,
                payload={
                    "capability_key": result.capability_key,
                    "ok": result.ok,
                    "status_code": result.status_code,
                },
                success=result.ok,
                capability_result=result,
            )
            observations.append(observation)
            run = await self._append_step(
                request=request,
                run=run,
                step_kind=PlanRunStepKind.OBSERVATION,
                payload=_serialize_observation(observation),
            )
        return tuple(observations)

    async def _synthesize_response(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        decision: PlanDecision,
    ) -> list[dict]:
        policy = run.policy
        synthesizer = self._select_response_synthesizer(policy)
        if synthesizer is None:
            if decision.response_payloads:
                return [dict(item) for item in decision.response_payloads]
            if decision.response_text is None and decision.completion is not None:
                content = decision.completion.content
                if isinstance(content, str):
                    return [{"type": "text", "content": content}]
                return []
            return (
                []
                if decision.response_text is None
                else [{"type": "text", "content": decision.response_text}]
            )
        return list(
            await synthesizer.synthesize(
                request,
                run,
                decision,
                policy=policy,
            )
        )

    def _select_response_synthesizer(self, policy: AgentRuntimePolicy):
        synthesizers = list(getattr(self._registry(), "response_synthesizers", []) or [])
        if not synthesizers:
            return None
        preferred = _normalize_optional_text(policy.response_synthesizer_key)
        if preferred is not None:
            for synthesizer in synthesizers:
                if _normalize_optional_text(getattr(synthesizer, "name", None)) == preferred:
                    return synthesizer
        return synthesizers[0]

    async def _spawn_background_run(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        decision: PlanDecision,
    ) -> str:
        background_payload = dict(decision.background_payload or {})
        forwarded_metadata = dict(request.metadata)
        forwarded_metadata.pop("agent_lineage", None)
        forwarded_metadata.pop("agent_join_state", None)
        forwarded_metadata.pop("delegation", None)
        background_request = PlanRunRequest(
            mode=PlanRunMode.BACKGROUND,
            scope=request.scope,
            user_message=str(background_payload.get("user_message") or request.user_message),
            message_id=request.message_id,
            trace_id=request.trace_id,
            service_route_key=request.service_route_key,
            agent_key=request.agent_key or run.policy.agent_key,
            ingress_metadata=dict(request.ingress_metadata),
            metadata={
                **forwarded_metadata,
                "spawned_from_run_id": run.run_id,
                "background_payload": background_payload,
            },
        )
        background_run = await self._planning_engine_service.prepare_run(background_request)
        return background_run.run_id

    async def _mark_waiting(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        decision: PlanDecision,
    ) -> PlanOutcome:
        scheduler = getattr(self._registry(), "scheduler", None)
        wake_at = decision.wait_until
        if wake_at is None:
            wake_at = _utc_now() + timedelta(seconds=max(1, int(run.policy.wait_seconds_default)))
        if scheduler is not None:
            wake_at = await scheduler.schedule_wait(run=run, wake_at=wake_at)
        run.status = PlanRunStatus.WAITING
        run.state.status = PlanRunStatus.WAITING
        run.next_wakeup_at = wake_at
        run = await self._plan_run_store_service.save_run(run)
        outcome = PlanOutcome(
            status=PlanOutcomeStatus.WAITING,
            metadata={
                "run_id": run.run_id,
                "next_wakeup_at": None if wake_at is None else wake_at.isoformat(),
            },
        )
        await self._record_outcome(request=request, run=run, outcome=outcome)
        return outcome

    async def _finalize_terminal(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        outcome: PlanOutcome,
    ) -> PlanOutcome:
        finalized_outcome = await self._plan_run_store_service.finalize_run(
            run_id=run.run_id,
            outcome=outcome,
        )
        run.status = _status_from_outcome(finalized_outcome)
        run.state.status = run.status
        run.final_outcome = finalized_outcome
        run.lease = None
        run.next_wakeup_at = None
        run = await self._reload_run_handle(run, operation="terminal finalization")
        updated_run = await self._planning_engine_service.finalize_run(
            request,
            run,
            finalized_outcome,
        )
        await self._record_outcome(
            request=request,
            run=updated_run,
            outcome=finalized_outcome,
        )
        return finalized_outcome

    async def _append_step(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        step_kind: PlanRunStepKind,
        payload: dict[str, Any],
    ) -> PreparedPlanRun:
        step = PlanRunStep(
            run_id=run.run_id,
            sequence_no=run.cursor.next_sequence_no,
            step_kind=step_kind,
            payload=payload,
            occurred_at=_utc_now(),
        )
        cursor = await self._plan_run_store_service.append_step(run_id=run.run_id, step=step)
        run.cursor = cursor
        run = await self._reload_run_handle(run, operation=f"{step_kind.value} step append")
        for trace_sink in list(getattr(self._registry(), "trace_sinks", []) or []):
            try:
                await trace_sink.record_step(request=request, run=run, step=step)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._logging_gateway.warning(
                    "Agent trace sink failed during step recording "
                    f"(run_id={run.run_id} error={type(exc).__name__}: {exc})."
                )
        return run

    @staticmethod
    def _apply_refreshed_run(
        run: PreparedPlanRun,
        refreshed_run: PreparedPlanRun,
    ) -> PreparedPlanRun:
        for field_def in fields(PreparedPlanRun):
            setattr(run, field_def.name, getattr(refreshed_run, field_def.name))
        return run

    async def _reload_run_handle(
        self,
        run: PreparedPlanRun,
        *,
        operation: str,
    ) -> PreparedPlanRun:
        loader = getattr(self._plan_run_store_service, "load_run", None)
        if loader is None:
            return run
        loaded = loader(run.run_id)
        if not inspect.isawaitable(loaded):
            return run
        refreshed_run = await loaded
        if refreshed_run is None:
            raise RuntimeError(
                "Agent runtime run refresh failed during "
                f"{operation} (run_id={run.run_id})."
            )
        return self._apply_refreshed_run(run, refreshed_run)

    async def _record_outcome(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        outcome: PlanOutcome,
    ) -> None:
        for trace_sink in list(getattr(self._registry(), "trace_sinks", []) or []):
            try:
                await trace_sink.record_outcome(request=request, run=run, outcome=outcome)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._logging_gateway.warning(
                    "Agent trace sink failed during outcome recording "
                    f"(run_id={run.run_id} error={type(exc).__name__}: {exc})."
                )

    async def _list_due_runs(
        self,
        *,
        limit: int,
        now: datetime | None,
    ) -> list[PreparedPlanRun]:
        scheduler = getattr(self._registry(), "scheduler", None)
        if scheduler is None:
            return await self._plan_run_store_service.list_runnable_runs(limit=limit, now=now)

        run_ids = await scheduler.due_run_ids(limit=limit, now=now)
        runs: list[PreparedPlanRun] = []
        for run_id in run_ids:
            loaded = await self._plan_run_store_service.load_run(run_id)
            if loaded is not None:
                runs.append(loaded)
        return runs
