"""Commit and outcome primitives for the context runtime."""

from __future__ import annotations

__all__ = ["ContextCommitResult", "TurnOutcome"]

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mugen.core.contract.context.memory import MemoryWrite


class TurnOutcome(str, Enum):
    """Normalized turn completion outcomes for commit logic."""

    COMPLETED = "completed"
    COMPLETION_FAILED = "completion_failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    NO_RESPONSE = "no_response"


@dataclass(frozen=True, slots=True)
class ContextCommitResult:
    """Result emitted after commit-phase persistence is completed."""

    commit_token: str
    state_revision: int | None = None
    memory_writes: tuple[MemoryWrite, ...] = ()
    cache_updates: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
