"""Bounded conversation control state primitives."""

from __future__ import annotations

__all__ = ["ContextState"]

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextState:
    """Bounded control state maintained per scoped conversation."""

    current_objective: str | None = None
    entities: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    unresolved_slots: list[str] = field(default_factory=list)
    commitments: list[str] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)
    routing: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    revision: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
