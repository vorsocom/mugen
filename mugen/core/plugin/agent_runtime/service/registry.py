"""Runtime component registry for the agent_runtime plugin."""

from __future__ import annotations

__all__ = ["AgentComponentRegistry"]

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentComponentRegistry:
    """Shared runtime registry consumed lazily by core agent services."""

    planners: list[Any] = field(default_factory=list)
    evaluators: list[Any] = field(default_factory=list)
    capability_providers: list[Any] = field(default_factory=list)
    execution_guards: list[Any] = field(default_factory=list)
    response_synthesizers: list[Any] = field(default_factory=list)
    trace_sinks: list[Any] = field(default_factory=list)
    policy_resolver: Any | None = None
    run_store: Any | None = None
    scheduler: Any | None = None
    _single_slot_owners: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )

    def register_planner(self, planner: Any) -> None:
        self.planners.append(planner)

    def register_evaluator(self, evaluator: Any) -> None:
        self.evaluators.append(evaluator)

    def register_capability_provider(self, provider: Any) -> None:
        self.capability_providers.append(provider)

    def register_execution_guard(self, guard: Any) -> None:
        self.execution_guards.append(guard)

    def register_response_synthesizer(self, synthesizer: Any) -> None:
        self.response_synthesizers.append(synthesizer)

    def register_trace_sink(self, trace_sink: Any) -> None:
        self.trace_sinks.append(trace_sink)

    def set_policy_resolver(self, policy_resolver: Any, *, owner: str | None = None) -> None:
        self._set_single_slot(
            slot_name="policy_resolver",
            value=policy_resolver,
            owner=owner,
        )

    def set_run_store(self, run_store: Any, *, owner: str | None = None) -> None:
        self._set_single_slot(
            slot_name="run_store",
            value=run_store,
            owner=owner,
        )

    def set_scheduler(self, scheduler: Any, *, owner: str | None = None) -> None:
        self._set_single_slot(
            slot_name="scheduler",
            value=scheduler,
            owner=owner,
        )

    def _set_single_slot(
        self,
        *,
        slot_name: str,
        value: Any,
        owner: str | None,
    ) -> None:
        current = getattr(self, slot_name)
        resolved_owner = self._owner_name(owner=owner, value=value)
        existing_owner = self._single_slot_owners.get(slot_name)
        if current is not None and current is not value:
            raise RuntimeError(
                "Agent component registry already has "
                f"{slot_name!r} owned by {existing_owner!r}; "
                f"attempted owner {resolved_owner!r}."
            )
        setattr(self, slot_name, value)
        self._single_slot_owners[slot_name] = resolved_owner

    @staticmethod
    def _owner_name(*, owner: str | None, value: Any) -> str:
        if isinstance(owner, str) and owner.strip() != "":
            return owner.strip()
        return f"{type(value).__module__}.{type(value).__qualname__}"
