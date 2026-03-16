"""Ports for context runtime engines and collaborators."""

from __future__ import annotations

__all__ = [
    "IContextArtifactRenderer",
    "IContextCache",
    "IContextCommitStore",
    "IContextContributor",
    "IContextEngine",
    "IContextGuard",
    "IContextPolicyResolver",
    "IContextRanker",
    "IContextStateStore",
    "IContextTraceSink",
    "IMemoryWriter",
]

from abc import ABC, abstractmethod
from typing import Any

from mugen.core.contract.context.artifact import ContextCandidate, ContextGuardResult
from mugen.core.contract.context.bundle import PreparedContextTurn
from mugen.core.contract.context.commit import ContextCommitCheck
from mugen.core.contract.context.memory import MemoryWrite
from mugen.core.contract.context.policy import ContextPolicy
from mugen.core.contract.context.result import ContextCommitResult, TurnOutcome
from mugen.core.contract.context.state import ContextState
from mugen.core.contract.context.turn import ContextTurnRequest
from mugen.core.contract.gateway.completion import CompletionMessage, CompletionResponse


class IContextEngine(ABC):
    """Two-phase runtime boundary for context preparation and commit."""

    @abstractmethod
    async def prepare_turn(self, request: ContextTurnRequest) -> PreparedContextTurn:
        """Prepare context, compile completion request, and return commit handle."""

    @abstractmethod
    async def commit_turn(
        self,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
    ) -> ContextCommitResult:
        """Persist post-turn state, memory, trace, and cache updates."""


class IContextContributor(ABC):
    """Provider-neutral context candidate source."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable contributor identifier used by bindings and traces."""

    @abstractmethod
    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        """Collect typed candidates for the current turn."""


class IContextGuard(ABC):
    """Guard pass that may redact, reject, or veto candidates."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable guard identifier used in traces."""

    @abstractmethod
    async def apply(
        self,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate] | ContextGuardResult:
        """Apply guard decisions to candidate artifacts."""


class IContextRanker(ABC):
    """Ranker that scores candidates without owning storage or retrieval."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable ranker identifier used in traces."""

    @abstractmethod
    async def rank(
        self,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        """Return ranked candidates with updated score metadata."""


class IContextArtifactRenderer(ABC):
    """Renderer for one render_class of selected context artifacts."""

    @property
    @abstractmethod
    def render_class(self) -> str:
        """Stable render-class identifier used by the compiler."""

    @abstractmethod
    async def render(
        self,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        *,
        policy: ContextPolicy,
    ) -> list[CompletionMessage]:
        """Render selected candidates into normalized completion messages."""


class IMemoryWriter(ABC):
    """Post-turn writer for derived long-term memory."""

    @abstractmethod
    async def persist(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
    ) -> list[MemoryWrite]:
        """Persist memory derived from final turn outcome."""


class IContextCache(ABC):
    """Optional pluggable cache service for context working sets and hints."""

    @abstractmethod
    async def get(self, *, namespace: str, key: str) -> Any:
        """Fetch one cached value."""

    @abstractmethod
    async def put(
        self,
        *,
        namespace: str,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        """Persist one cached value."""

    @abstractmethod
    async def invalidate(self, *, namespace: str, key_prefix: str) -> int:
        """Invalidate one namespace partition by key prefix."""


class IContextTraceSink(ABC):
    """Trace sink for prepare/commit observability and provenance."""

    @abstractmethod
    async def record_prepare(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
    ) -> None:
        """Record prepare-phase trace data."""

    @abstractmethod
    async def record_commit(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
        result: ContextCommitResult,
    ) -> None:
        """Record commit-phase trace data."""


class IContextPolicyResolver(ABC):
    """Resolver for scope-aware context policy selection."""

    @abstractmethod
    async def resolve_policy(
        self,
        request: ContextTurnRequest,
    ) -> ContextPolicy:
        """Resolve the effective policy for one context turn."""


class IContextStateStore(ABC):
    """Store for bounded scope-partitioned context state."""

    @abstractmethod
    async def load(self, request: ContextTurnRequest) -> ContextState | None:
        """Load the current bounded control state for a turn scope."""

    @abstractmethod
    async def save(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
    ) -> ContextState:
        """Persist updated bounded control state for a completed turn."""

    @abstractmethod
    async def clear(self, request: ContextTurnRequest) -> None:
        """Reset the bounded state for a scoped conversation."""


class IContextCommitStore(ABC):
    """Store that issues, validates, and finalizes commit tokens."""

    @abstractmethod
    async def issue_token(
        self,
        *,
        request: ContextTurnRequest,
        prepared_fingerprint: str,
        ttl_seconds: int | None = None,
    ) -> str:
        """Issue one opaque commit token for a prepared turn."""

    @abstractmethod
    async def begin_commit(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        prepared_fingerprint: str,
    ) -> ContextCommitCheck:
        """Validate a prepared token and acquire the right to commit once."""

    @abstractmethod
    async def complete_commit(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        prepared_fingerprint: str,
        result: ContextCommitResult,
    ) -> None:
        """Finalize a commit token after successful persistence."""

    @abstractmethod
    async def fail_commit(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        prepared_fingerprint: str,
        error_message: str,
    ) -> None:
        """Mark a prepared token as failed after commit persistence aborts."""
