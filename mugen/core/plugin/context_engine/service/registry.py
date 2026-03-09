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
    renderers: list[Any] = field(default_factory=list)
    trace_sinks: list[Any] = field(default_factory=list)
    policy_resolver: Any | None = None
    state_store: Any | None = None
    memory_writer: Any | None = None
    cache: Any | None = None
    commit_store: Any | None = None
    _single_slot_owners: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _renderer_owners: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )

    def register_contributor(self, contributor: Any) -> None:
        self.contributors.append(contributor)

    def register_guard(self, guard: Any) -> None:
        self.guards.append(guard)

    def register_ranker(self, ranker: Any) -> None:
        self.rankers.append(ranker)

    def register_renderer(self, renderer: Any, *, owner: str | None = None) -> None:
        render_class = str(getattr(renderer, "render_class", "") or "").strip()
        if render_class == "":
            raise RuntimeError("Context renderer registrations require render_class.")
        resolved_owner = self._owner_name(owner=owner, value=renderer)
        existing_owner = self._renderer_owners.get(render_class)
        if existing_owner is not None and existing_owner != resolved_owner:
            raise RuntimeError(
                "Context component registry already has renderer "
                f"{render_class!r} owned by {existing_owner!r}; "
                f"attempted owner {resolved_owner!r}."
            )
        self.renderers = [
            item
            for item in self.renderers
            if str(getattr(item, "render_class", "") or "").strip() != render_class
        ]
        self.renderers.append(renderer)
        self._renderer_owners[render_class] = resolved_owner

    def register_trace_sink(self, trace_sink: Any) -> None:
        self.trace_sinks.append(trace_sink)

    def set_policy_resolver(
        self,
        policy_resolver: Any,
        *,
        owner: str | None = None,
    ) -> None:
        self._set_single_slot(
            slot_name="policy_resolver",
            value=policy_resolver,
            owner=owner,
        )

    def set_state_store(
        self,
        state_store: Any,
        *,
        owner: str | None = None,
    ) -> None:
        self._set_single_slot(
            slot_name="state_store",
            value=state_store,
            owner=owner,
        )

    def set_memory_writer(
        self,
        memory_writer: Any,
        *,
        owner: str | None = None,
    ) -> None:
        self._set_single_slot(
            slot_name="memory_writer",
            value=memory_writer,
            owner=owner,
        )

    def set_cache(
        self,
        cache: Any,
        *,
        owner: str | None = None,
    ) -> None:
        self._set_single_slot(
            slot_name="cache",
            value=cache,
            owner=owner,
        )

    def set_commit_store(
        self,
        commit_store: Any,
        *,
        owner: str | None = None,
    ) -> None:
        self._set_single_slot(
            slot_name="commit_store",
            value=commit_store,
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
                "Context component registry already has "
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
