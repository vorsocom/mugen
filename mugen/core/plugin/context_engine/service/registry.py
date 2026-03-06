"""Runtime component registry for the context_engine plugin."""

from __future__ import annotations

__all__ = ["ContextComponentRegistry"]

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextComponentRegistry:
    """Shared runtime registry consumed lazily by the core context engine."""

    contributors: list[Any] = field(default_factory=list)
    guards: list[Any] = field(default_factory=list)
    rankers: list[Any] = field(default_factory=list)
    trace_sinks: list[Any] = field(default_factory=list)
    policy_resolver: Any | None = None
    state_store: Any | None = None
    memory_writer: Any | None = None
    cache: Any | None = None

    def register_contributor(self, contributor: Any) -> None:
        self.contributors.append(contributor)

    def register_guard(self, guard: Any) -> None:
        self.guards.append(guard)

    def register_ranker(self, ranker: Any) -> None:
        self.rankers.append(ranker)

    def register_trace_sink(self, trace_sink: Any) -> None:
        self.trace_sinks.append(trace_sink)

    def set_policy_resolver(self, policy_resolver: Any) -> None:
        self.policy_resolver = policy_resolver

    def set_state_store(self, state_store: Any) -> None:
        self.state_store = state_store

    def set_memory_writer(self, memory_writer: Any) -> None:
        self.memory_writer = memory_writer

    def set_cache(self, cache: Any) -> None:
        self.cache = cache
