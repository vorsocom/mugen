"""Stable agent-runtime contracts and intermediate representations."""

from __future__ import annotations

__all__ = [
    "AgentRuntimePolicy",
    "CapabilityDescriptor",
    "CapabilityInvocation",
    "CapabilityResult",
    "EvaluationRequest",
    "EvaluationResult",
    "EvaluationStatus",
    "PlanDecision",
    "PlanDecisionKind",
    "PlanLease",
    "PlanObservation",
    "PlanOutcome",
    "PlanOutcomeStatus",
    "PlanRunCursor",
    "PlanRunMode",
    "PlanRunRequest",
    "PlanRunState",
    "PlanRunStatus",
    "PlanRunStep",
    "PlanRunStepKind",
    "PreparedPlanRun",
]

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from mugen.core.contract.context import ContextScope, PreparedContextTurn
from mugen.core.contract.gateway.completion import CompletionResponse


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Agent-runtime text fields must be strings or None.")
    normalized = value.strip()
    return normalized or None


def _route_key_from_metadata(metadata: dict[str, Any]) -> str | None:
    ingress_route = metadata.get("ingress_route")
    route_value = None
    if isinstance(ingress_route, dict):
        route_value = _normalize_optional_text(ingress_route.get("service_route_key"))
    if route_value is not None:
        return route_value
    return _normalize_optional_text(metadata.get("service_route_key"))


class PlanRunMode(str, Enum):
    """Execution mode for one plan run."""

    CURRENT_TURN = "current_turn"
    BACKGROUND = "background"


class PlanRunStatus(str, Enum):
    """Lifecycle status for one plan run."""

    PREPARED = "prepared"
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    HANDOFF = "handoff"
    STOPPED = "stopped"


class PlanDecisionKind(str, Enum):
    """High-level planner outputs."""

    RESPOND = "respond"
    EXECUTE_ACTION = "execute_action"
    WAIT = "wait"
    HANDOFF = "handoff"
    SPAWN_BACKGROUND = "spawn_background"
    STOP = "stop"


class EvaluationStatus(str, Enum):
    """Evaluator decision for a step, response, or full run."""

    PASS = "pass"
    FAIL = "fail"
    RETRY = "retry"
    REPLAN = "replan"
    ESCALATE = "escalate"


class PlanOutcomeStatus(str, Enum):
    """Terminal or externally visible outcome for a plan run."""

    COMPLETED = "completed"
    FAILED = "failed"
    HANDOFF = "handoff"
    WAITING = "waiting"
    SPAWNED_BACKGROUND = "spawned_background"
    STOPPED = "stopped"


class PlanRunStepKind(str, Enum):
    """Append-only step-history kinds."""

    DECISION = "decision"
    OBSERVATION = "observation"
    EVALUATION = "evaluation"
    EFFECT = "effect"


@dataclass(slots=True)
class AgentRuntimePolicy:
    """Code-configured runtime policy snapshot for one request/run."""

    enabled: bool = False
    current_turn_enabled: bool = False
    background_enabled: bool = False
    planner_key: str = "llm_default"
    evaluator_key: str = "llm_default"
    response_synthesizer_key: str = "text_default"
    capability_allow: tuple[str, ...] = ()
    max_iterations: int = 4
    max_background_iterations: int = 8
    lease_seconds: int = 60
    wait_seconds_default: int = 30
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CapabilityDescriptor:
    """Planner-visible capability surface."""

    key: str
    title: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    idempotency_key_field: str | None = None
    side_effect_class: str = "read"
    approval_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_key = _normalize_optional_text(self.key)
        normalized_title = _normalize_optional_text(self.title)
        if normalized_key is None:
            raise ValueError("CapabilityDescriptor.key is required.")
        if normalized_title is None:
            raise ValueError("CapabilityDescriptor.title is required.")
        self.key = normalized_key
        self.title = normalized_title
        self.description = _normalize_optional_text(self.description)
        self.idempotency_key_field = _normalize_optional_text(self.idempotency_key_field)


@dataclass(slots=True)
class CapabilityInvocation:
    """One capability execution request."""

    capability_key: str
    arguments: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        capability_key = _normalize_optional_text(self.capability_key)
        if capability_key is None:
            raise ValueError("CapabilityInvocation.capability_key is required.")
        self.capability_key = capability_key
        self.idempotency_key = _normalize_optional_text(self.idempotency_key)
        if not isinstance(self.arguments, dict):
            raise TypeError("CapabilityInvocation.arguments must be a dict.")


@dataclass(slots=True)
class CapabilityResult:
    """Normalized capability execution result."""

    capability_key: str
    ok: bool
    result: Any = None
    status_code: int | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        capability_key = _normalize_optional_text(self.capability_key)
        if capability_key is None:
            raise ValueError("CapabilityResult.capability_key is required.")
        self.capability_key = capability_key
        self.error_message = _normalize_optional_text(self.error_message)


@dataclass(slots=True)
class PlanRunRequest:
    """Normalized request envelope for current-turn or background planning."""

    mode: PlanRunMode
    scope: ContextScope
    user_message: str
    message_id: str | None = None
    trace_id: str | None = None
    service_route_key: str | None = None
    ingress_metadata: dict[str, Any] = field(default_factory=dict)
    prepared_context: PreparedContextTurn | None = None
    available_capabilities: tuple[CapabilityDescriptor, ...] = ()
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.mode, PlanRunMode):
            self.mode = PlanRunMode(str(self.mode))
        if not isinstance(self.scope, ContextScope):
            raise TypeError("PlanRunRequest.scope must be a ContextScope.")
        user_message = _normalize_optional_text(self.user_message)
        if user_message is None:
            raise ValueError("PlanRunRequest.user_message is required.")
        self.user_message = user_message
        self.message_id = _normalize_optional_text(self.message_id)
        self.trace_id = _normalize_optional_text(self.trace_id)
        if not isinstance(self.ingress_metadata, dict):
            raise TypeError("PlanRunRequest.ingress_metadata must be a dict.")
        self.service_route_key = _normalize_optional_text(self.service_route_key)
        if self.service_route_key is None:
            self.service_route_key = _route_key_from_metadata(self.ingress_metadata)
        self.run_id = _normalize_optional_text(self.run_id)
        self.available_capabilities = tuple(self.available_capabilities or ())


@dataclass(slots=True)
class PlanRunState:
    """Durable mutable state for one agent run."""

    goal: str
    status: PlanRunStatus = PlanRunStatus.PREPARED
    iteration_count: int = 0
    background_iteration_count: int = 0
    last_response_text: str | None = None
    last_error: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        goal = _normalize_optional_text(self.goal)
        if goal is None:
            raise ValueError("PlanRunState.goal is required.")
        self.goal = goal
        if not isinstance(self.status, PlanRunStatus):
            self.status = PlanRunStatus(str(self.status))
        self.last_response_text = _normalize_optional_text(self.last_response_text)
        self.last_error = _normalize_optional_text(self.last_error)
        self.summary = _normalize_optional_text(self.summary)


@dataclass(slots=True)
class PlanLease:
    """Lease state for resumable background work."""

    owner: str
    expires_at: datetime

    def __post_init__(self) -> None:
        owner = _normalize_optional_text(self.owner)
        if owner is None:
            raise ValueError("PlanLease.owner is required.")
        self.owner = owner
        if not isinstance(self.expires_at, datetime):
            raise TypeError("PlanLease.expires_at must be a datetime.")


@dataclass(slots=True)
class PlanRunCursor:
    """Append-only cursor over plan-run history."""

    run_id: str
    next_sequence_no: int = 1
    status: PlanRunStatus = PlanRunStatus.PREPARED

    def __post_init__(self) -> None:
        run_id = _normalize_optional_text(self.run_id)
        if run_id is None:
            raise ValueError("PlanRunCursor.run_id is required.")
        self.run_id = run_id
        if not isinstance(self.status, PlanRunStatus):
            self.status = PlanRunStatus(str(self.status))


@dataclass(slots=True)
class PlanObservation:
    """One observation captured between planner steps."""

    kind: str
    summary: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    success: bool | None = None
    capability_result: CapabilityResult | None = None
    completion: CompletionResponse | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = _normalize_optional_text(self.kind)
        if kind is None:
            raise ValueError("PlanObservation.kind is required.")
        self.kind = kind
        self.summary = _normalize_optional_text(self.summary)
        if not isinstance(self.payload, dict):
            raise TypeError("PlanObservation.payload must be a dict.")


@dataclass(slots=True)
class PlanDecision:
    """Planner-selected next action."""

    kind: PlanDecisionKind
    response_text: str | None = None
    response_payloads: tuple[dict[str, Any], ...] = ()
    capability_invocations: tuple[CapabilityInvocation, ...] = ()
    wait_until: datetime | None = None
    handoff_reason: str | None = None
    background_payload: dict[str, Any] | None = None
    completion: CompletionResponse | None = None
    rationale_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PlanDecisionKind):
            self.kind = PlanDecisionKind(str(self.kind))
        self.response_text = _normalize_optional_text(self.response_text)
        self.handoff_reason = _normalize_optional_text(self.handoff_reason)
        self.rationale_summary = _normalize_optional_text(self.rationale_summary)
        self.response_payloads = tuple(self.response_payloads or ())
        self.capability_invocations = tuple(self.capability_invocations or ())


@dataclass(slots=True)
class EvaluationRequest:
    """Shared evaluator request envelope."""

    request: PlanRunRequest
    run: PreparedPlanRun
    decision: PlanDecision | None = None
    observations: tuple[PlanObservation, ...] = ()
    draft_response_text: str | None = None
    final_user_responses: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request, PlanRunRequest):
            raise TypeError("EvaluationRequest.request must be a PlanRunRequest.")
        if not isinstance(self.run, PreparedPlanRun):
            raise TypeError("EvaluationRequest.run must be a PreparedPlanRun.")
        self.draft_response_text = _normalize_optional_text(self.draft_response_text)
        self.observations = tuple(self.observations or ())
        self.final_user_responses = tuple(self.final_user_responses or ())


@dataclass(slots=True)
class EvaluationResult:
    """Structured evaluator output."""

    status: EvaluationStatus
    reasons: tuple[str, ...] = ()
    scores: dict[str, float] = field(default_factory=dict)
    recommended_decision: PlanDecisionKind | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, EvaluationStatus):
            self.status = EvaluationStatus(str(self.status))
        self.reasons = tuple(
            item for item in (_normalize_optional_text(reason) for reason in self.reasons)
            if item is not None
        )
        if self.recommended_decision is not None and not isinstance(
            self.recommended_decision,
            PlanDecisionKind,
        ):
            self.recommended_decision = PlanDecisionKind(str(self.recommended_decision))


@dataclass(slots=True)
class PlanOutcome:
    """Final or externally-visible result from the agent runtime."""

    status: PlanOutcomeStatus
    final_user_responses: tuple[dict[str, Any], ...] = ()
    assistant_response: str | None = None
    completion: CompletionResponse | None = None
    background_run_id: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, PlanOutcomeStatus):
            self.status = PlanOutcomeStatus(str(self.status))
        self.final_user_responses = tuple(self.final_user_responses or ())
        self.assistant_response = _normalize_optional_text(self.assistant_response)
        self.background_run_id = _normalize_optional_text(self.background_run_id)
        self.error_message = _normalize_optional_text(self.error_message)


@dataclass(slots=True)
class PlanRunStep:
    """One append-only persisted run step."""

    run_id: str
    sequence_no: int
    step_kind: PlanRunStepKind
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        run_id = _normalize_optional_text(self.run_id)
        if run_id is None:
            raise ValueError("PlanRunStep.run_id is required.")
        self.run_id = run_id
        if not isinstance(self.step_kind, PlanRunStepKind):
            self.step_kind = PlanRunStepKind(str(self.step_kind))
        if not isinstance(self.payload, dict):
            raise TypeError("PlanRunStep.payload must be a dict.")


@dataclass(slots=True)
class PreparedPlanRun:
    """Prepared run handle returned by the planning engine and run store."""

    run_id: str
    mode: PlanRunMode
    status: PlanRunStatus
    state: PlanRunState
    policy: AgentRuntimePolicy
    request_snapshot: dict[str, Any]
    cursor: PlanRunCursor
    service_route_key: str | None = None
    next_wakeup_at: datetime | None = None
    lease: PlanLease | None = None
    final_outcome: PlanOutcome | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        run_id = _normalize_optional_text(self.run_id)
        if run_id is None:
            raise ValueError("PreparedPlanRun.run_id is required.")
        self.run_id = run_id
        if not isinstance(self.mode, PlanRunMode):
            self.mode = PlanRunMode(str(self.mode))
        if not isinstance(self.status, PlanRunStatus):
            self.status = PlanRunStatus(str(self.status))
        if not isinstance(self.state, PlanRunState):
            raise TypeError("PreparedPlanRun.state must be a PlanRunState.")
        if not isinstance(self.policy, AgentRuntimePolicy):
            raise TypeError("PreparedPlanRun.policy must be an AgentRuntimePolicy.")
        if not isinstance(self.cursor, PlanRunCursor):
            raise TypeError("PreparedPlanRun.cursor must be a PlanRunCursor.")
        if not isinstance(self.request_snapshot, dict):
            raise TypeError("PreparedPlanRun.request_snapshot must be a dict.")
        self.service_route_key = _normalize_optional_text(self.service_route_key)
