"""Commit-token lifecycle primitives for the context runtime."""

from __future__ import annotations

__all__ = [
    "ContextCommitCheck",
    "ContextCommitState",
]

from dataclasses import dataclass
from enum import Enum

from mugen.core.contract.context.result import ContextCommitResult


class ContextCommitState(str, Enum):
    """Stable lifecycle states for issued context commit tokens."""

    PREPARED = "prepared"
    COMMITTING = "committing"
    COMMITTED = "committed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ContextCommitCheck:
    """Result of validating or acquiring a commit token for commit_turn."""

    state: ContextCommitState
    replay_result: ContextCommitResult | None = None
