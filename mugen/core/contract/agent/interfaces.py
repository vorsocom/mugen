"""Ports for agent planning, evaluation, execution, and runtime orchestration."""

from __future__ import annotations

__all__ = [
    "IAgentExecutor",
    "IAgentPolicyResolver",
    "IAgentRuntime",
    "IAgentScheduler",
    "IAgentTraceSink",
    "ICapabilityProvider",
    "IEvaluationEngine",
    "IEvaluatorStrategy",
    "IExecutionGuard",
    "IPlanRunStore",
    "IPlanningEngine",
    "IPlannerStrategy",
    "IResponseSynthesizer",
]

from abc import ABC, abstractmethod
from datetime import datetime

from mugen.core.contract.agent.types import (
    AgentRuntimePolicy,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityResult,
    EvaluationRequest,
    EvaluationResult,
    PlanDecision,
    PlanLease,
    PlanOutcome,
    PlanRunCursor,
    PlanRunRequest,
    PlanRunStep,
    PreparedPlanRun,
)


class IAgentPolicyResolver(ABC):
    """Resolve code-configured agent-runtime policy for one request."""

    @abstractmethod
    async def resolve_policy(self, request: PlanRunRequest) -> AgentRuntimePolicy:
        """Resolve the effective policy for one run request."""


class IPlannerStrategy(ABC):
    """Named planning strategy used by the first-class planning engine."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable strategy identifier."""

    @abstractmethod
    async def next_decision(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        observations: tuple,
        *,
        policy: AgentRuntimePolicy,
    ) -> PlanDecision:
        """Produce the next planner decision for one run iteration."""

    @abstractmethod
    async def finalize_run(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        outcome: PlanOutcome,
        *,
        policy: AgentRuntimePolicy,
    ) -> None:
        """Perform planner-specific finalization hooks."""


class IPlanningEngine(ABC):
    """First-class planning-engine boundary."""

    @abstractmethod
    async def prepare_run(self, request: PlanRunRequest) -> PreparedPlanRun:
        """Prepare or resume one run and return its durable handle."""

    @abstractmethod
    async def next_decision(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        observations: tuple,
    ) -> PlanDecision:
        """Resolve the next plan decision using the selected strategy."""

    @abstractmethod
    async def finalize_run(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        outcome: PlanOutcome,
    ) -> PreparedPlanRun:
        """Persist any planner-side finalization state."""


class IEvaluatorStrategy(ABC):
    """Named evaluation strategy used by the first-class evaluation engine."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable strategy identifier."""

    @abstractmethod
    async def evaluate_step(
        self,
        request: EvaluationRequest,
        *,
        policy: AgentRuntimePolicy,
    ) -> EvaluationResult:
        """Evaluate one non-terminal step."""

    @abstractmethod
    async def evaluate_response(
        self,
        request: EvaluationRequest,
        *,
        policy: AgentRuntimePolicy,
    ) -> EvaluationResult:
        """Evaluate one draft user response."""

    @abstractmethod
    async def evaluate_run(
        self,
        request: EvaluationRequest,
        outcome: PlanOutcome,
        *,
        policy: AgentRuntimePolicy,
    ) -> EvaluationResult:
        """Evaluate the final run outcome."""


class IEvaluationEngine(ABC):
    """First-class evaluation-engine boundary."""

    @abstractmethod
    async def evaluate_step(self, request: EvaluationRequest) -> EvaluationResult:
        """Evaluate one non-terminal step."""

    @abstractmethod
    async def evaluate_response(self, request: EvaluationRequest) -> EvaluationResult:
        """Evaluate one draft response."""

    @abstractmethod
    async def evaluate_run(
        self,
        request: EvaluationRequest,
        outcome: PlanOutcome,
    ) -> EvaluationResult:
        """Evaluate the final run outcome."""


class ICapabilityProvider(ABC):
    """Provider-neutral capability catalog and execution adapter."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider identifier."""

    @abstractmethod
    async def list_capabilities(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        *,
        policy: AgentRuntimePolicy,
    ) -> list[CapabilityDescriptor]:
        """List capabilities exposed by this provider."""

    @abstractmethod
    def supports(self, capability_key: str) -> bool:
        """Return whether this provider can execute one capability key."""

    @abstractmethod
    async def execute(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        invocation: CapabilityInvocation,
        descriptor: CapabilityDescriptor,
        *,
        policy: AgentRuntimePolicy,
    ) -> CapabilityResult:
        """Execute one capability invocation."""


class IExecutionGuard(ABC):
    """Guardrail hook around capability execution."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable guard identifier."""

    @abstractmethod
    async def validate(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        invocation: CapabilityInvocation,
        descriptor: CapabilityDescriptor,
        *,
        policy: AgentRuntimePolicy,
    ) -> None:
        """Raise when one invocation should not be executed."""


class IAgentExecutor(ABC):
    """First-class capability execution boundary."""

    @abstractmethod
    async def list_capabilities(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
    ) -> list[CapabilityDescriptor]:
        """List planner-visible capabilities for one run."""

    @abstractmethod
    async def execute_capability(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        invocation: CapabilityInvocation,
    ) -> CapabilityResult:
        """Execute one normalized capability invocation."""


class IPlanRunStore(ABC):
    """Durable store for run state, leases, and append-only history."""

    @abstractmethod
    async def create_run(
        self,
        request: PlanRunRequest,
        *,
        state: object,
        policy: AgentRuntimePolicy,
    ) -> PreparedPlanRun:
        """Create a new durable run."""

    @abstractmethod
    async def load_run(self, run_id: str) -> PreparedPlanRun | None:
        """Load one durable run by id."""

    @abstractmethod
    async def save_run(self, run: PreparedPlanRun) -> PreparedPlanRun:
        """Persist the latest run state."""

    @abstractmethod
    async def append_step(
        self,
        *,
        run_id: str,
        step: PlanRunStep,
    ) -> PlanRunCursor:
        """Append one immutable step and return the updated cursor."""

    @abstractmethod
    async def acquire_lease(
        self,
        *,
        run_id: str,
        owner: str,
        lease_seconds: int,
    ) -> PlanLease | None:
        """Acquire the right to process one background run."""

    @abstractmethod
    async def release_lease(self, *, run_id: str, owner: str) -> None:
        """Release a previously acquired lease."""

    @abstractmethod
    async def list_runnable_runs(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[PreparedPlanRun]:
        """List runs that are due for background work."""

    @abstractmethod
    async def finalize_run(
        self,
        *,
        run_id: str,
        outcome: PlanOutcome,
    ) -> PlanOutcome:
        """Idempotently finalize one run."""

    @abstractmethod
    async def list_steps(self, *, run_id: str, limit: int | None = None) -> list[PlanRunStep]:
        """List append-only steps for one run."""


class IResponseSynthesizer(ABC):
    """Turn a planner decision into user-visible responses."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable synthesizer identifier."""

    @abstractmethod
    async def synthesize(
        self,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        decision: PlanDecision,
        *,
        policy: AgentRuntimePolicy,
    ) -> list[dict]:
        """Build final user responses for one decision."""


class IAgentTraceSink(ABC):
    """Trace sink for agent-run observability."""

    @abstractmethod
    async def record_step(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        step: PlanRunStep,
    ) -> None:
        """Record one append-only step."""

    @abstractmethod
    async def record_outcome(
        self,
        *,
        request: PlanRunRequest,
        run: PreparedPlanRun,
        outcome: PlanOutcome,
    ) -> None:
        """Record one terminal outcome."""


class IAgentScheduler(ABC):
    """Scheduler boundary for delayed background work."""

    @abstractmethod
    async def due_run_ids(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[str]:
        """Return due run ids ordered for execution."""

    @abstractmethod
    async def schedule_wait(
        self,
        *,
        run: PreparedPlanRun,
        wake_at: datetime | None,
    ) -> datetime | None:
        """Persist or normalize one wake-up timestamp."""


class IAgentRuntime(ABC):
    """Coordinator above planning, evaluation, execution, and run persistence."""

    @abstractmethod
    async def is_enabled_for_request(self, request: PlanRunRequest) -> bool:
        """Return whether agent runtime should own this request."""

    @abstractmethod
    async def run_current_turn(self, request: PlanRunRequest) -> PlanOutcome:
        """Execute the same-turn plan-act-evaluate loop."""

    @abstractmethod
    async def run_background_batch(
        self,
        *,
        owner: str,
        limit: int = 20,
        now: datetime | None = None,
    ) -> list[PlanOutcome]:
        """Resume background runs that are due."""
