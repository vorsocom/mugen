"""Prepared context bundle primitives."""

from __future__ import annotations

__all__ = ["ContextBundle", "PreparedContextTurn"]

from dataclasses import dataclass, field
from typing import Any

from mugen.core.contract.context.artifact import ContextCandidate
from mugen.core.contract.context.policy import ContextPolicy
from mugen.core.contract.context.state import ContextState
from mugen.core.contract.gateway.completion import CompletionRequest


@dataclass(frozen=True, slots=True)
class ContextBundle:
    """Structured context selection and trace state for one prepared turn."""

    policy: ContextPolicy
    state: ContextState | None
    selected_candidates: tuple[ContextCandidate, ...]
    dropped_candidates: tuple[ContextCandidate, ...]
    prefix_fingerprint: str | None = None
    cache_hints: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreparedContextTurn:
    """Prepare-phase output compiled to normalized completion request."""

    completion_request: CompletionRequest
    bundle: ContextBundle
    state_handle: str | None
    commit_token: str
    trace: dict[str, Any] = field(default_factory=dict)
