"""Default context-engine implementation."""

from __future__ import annotations

__all__ = ["DefaultContextEngine"]

from types import SimpleNamespace
from typing import Any

from mugen.core import di
from mugen.core.contract.context import (
    ContextBundle,
    ContextCandidate,
    ContextCommitResult,
    ContextPolicy,
    ContextSelectionReason,
    ContextState,
    ContextTurnRequest,
    IContextCache,
    IContextEngine,
    IContextPolicyResolver,
    IContextStateStore,
    IContextTraceSink,
    PreparedContextTurn,
    TurnOutcome,
)
from mugen.core.contract.gateway.completion import (
    CompletionMessage,
    CompletionRequest,
    CompletionResponse,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.utility.context_runtime import (
    messages_fingerprint,
    prefix_cache_key,
    retrieval_cache_key,
    scope_identity,
    scope_key,
    working_set_cache_key,
)


def _context_component_registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY)


class DefaultContextEngine(IContextEngine):
    """Default provider-neutral context runtime implementation."""

    _lane_priority = {
        "system_persona_policy": 0,
        "bounded_control_state": 1,
        "operational_overlay": 2,
        "recent_turn": 3,
        "evidence": 4,
    }

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway

    async def prepare_turn(self, request: ContextTurnRequest) -> PreparedContextTurn:
        registry = _context_component_registry_provider()
        policy_resolver = self._get_policy_resolver(registry)
        state_store = self._get_state_store(registry)

        policy = await policy_resolver.resolve_policy(request)
        state = await state_store.load(request)

        candidates, dropped_candidates = await self._collect_candidates(
            registry=registry,
            request=request,
            policy=policy,
            state=state,
        )
        guarded_candidates, guard_dropped = await self._apply_guards(
            registry=registry,
            request=request,
            candidates=candidates,
            policy=policy,
            state=state,
        )
        dropped_candidates.extend(guard_dropped)
        ranked_candidates = await self._apply_rankers(
            registry=registry,
            request=request,
            candidates=guarded_candidates,
            policy=policy,
            state=state,
        )

        selected_candidates, selection_dropped = self._select_candidates(
            candidates=ranked_candidates,
            policy=policy,
        )
        dropped_candidates.extend(selection_dropped)
        completion_request = self._compile_completion_request(
            request=request,
            policy=policy,
            state=state,
            selected_candidates=selected_candidates,
        )
        prefix_fingerprint = self._prefix_fingerprint(completion_request)
        cache_hints = {
            "prefix_fingerprint": prefix_fingerprint,
            "selected_artifact_ids": [
                candidate.artifact.artifact_id for candidate in selected_candidates
            ],
        }
        bundle = ContextBundle(
            policy=policy,
            state=state,
            selected_candidates=tuple(selected_candidates),
            dropped_candidates=tuple(dropped_candidates),
            prefix_fingerprint=prefix_fingerprint,
            cache_hints=cache_hints,
            trace=self._build_prepare_trace(
                request=request,
                selected_candidates=selected_candidates,
                dropped_candidates=dropped_candidates,
            ),
        )
        prepared = PreparedContextTurn(
            completion_request=completion_request,
            bundle=bundle,
            state_handle=scope_key(request.scope),
            commit_token=self._commit_token(request, prefix_fingerprint),
            trace=dict(bundle.trace),
        )

        cache = self._get_optional_cache(registry)
        if policy.cache_enabled and cache is not None:
            await cache.put(
                namespace="retrieval",
                key=retrieval_cache_key(request),
                value=self._serialize_candidates(selected_candidates),
                ttl_seconds=policy.retention.cache_ttl_seconds,
            )
            await cache.put(
                namespace="prefix_fingerprint",
                key=prefix_cache_key(request.scope, prefix_fingerprint),
                value={"prefix_fingerprint": prefix_fingerprint},
                ttl_seconds=policy.retention.cache_ttl_seconds,
            )

        await self._record_prepare(
            registry=registry,
            request=request,
            prepared=prepared,
            trace_enabled=policy.trace_enabled,
        )
        return prepared

    async def commit_turn(
        self,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
    ) -> ContextCommitResult:
        registry = _context_component_registry_provider()
        state_store = self._get_state_store(registry)

        self._validate_commit_token(request=request, prepared=prepared)
        state = await state_store.save(
            request=request,
            prepared=prepared,
            completion=completion,
            final_user_responses=final_user_responses,
            outcome=outcome,
        )
        memory_writer = getattr(registry, "memory_writer", None)
        memory_writes = []
        if memory_writer is not None:
            memory_writes = await memory_writer.persist(
                request=request,
                prepared=prepared,
                completion=completion,
                final_user_responses=final_user_responses,
                outcome=outcome,
            )

        cache_updates: dict[str, Any] = {}
        cache = self._get_optional_cache(registry)
        if prepared.bundle.policy.cache_enabled and cache is not None:
            working_set_key = working_set_cache_key(request.scope)
            await cache.put(
                namespace="working_set",
                key=working_set_key,
                value={
                    "state_revision": state.revision,
                    "prefix_fingerprint": prepared.bundle.prefix_fingerprint,
                },
                ttl_seconds=prepared.bundle.policy.retention.cache_ttl_seconds,
            )
            cache_updates["working_set"] = working_set_key

        result = ContextCommitResult(
            commit_token=prepared.commit_token,
            state_revision=state.revision,
            memory_writes=tuple(memory_writes),
            cache_updates=cache_updates,
        )
        await self._record_commit(
            registry=registry,
            request=request,
            prepared=prepared,
            completion=completion,
            final_user_responses=final_user_responses,
            outcome=outcome,
            result=result,
            trace_enabled=prepared.bundle.policy.trace_enabled,
        )
        return result

    def _compile_completion_request(
        self,
        *,
        request: ContextTurnRequest,
        policy: ContextPolicy,
        state: ContextState | None,
        selected_candidates: list[ContextCandidate],
    ) -> CompletionRequest:
        messages: list[CompletionMessage] = []

        system_payload = self._lane_payload(
            selected_candidates,
            lane="system_persona_policy",
        )
        if system_payload:
            messages.append(CompletionMessage(role="system", content=system_payload))

        state_payload = self._state_payload(state)
        if state_payload is not None:
            messages.append(CompletionMessage(role="system", content=state_payload))

        overlay_payload = self._lane_payload(
            selected_candidates,
            lane="operational_overlay",
        )
        if overlay_payload:
            messages.append(CompletionMessage(role="system", content=overlay_payload))

        evidence_payload = self._lane_payload(selected_candidates, lane="evidence")
        if evidence_payload:
            messages.append(CompletionMessage(role="system", content=evidence_payload))

        messages.extend(self._recent_turn_messages(selected_candidates))
        messages.append(
            CompletionMessage(
                role="user",
                content=self._user_message_payload(request),
            )
        )

        vendor_params = {
            "context_cache_hints": {
                "prefix_fingerprint": messages_fingerprint(messages[:-1]),
            }
        }
        if policy.metadata:
            vendor_params["context_policy"] = dict(policy.metadata)

        return CompletionRequest(messages=messages, vendor_params=vendor_params)

    async def _collect_candidates(
        self,
        *,
        registry: Any,
        request: ContextTurnRequest,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        candidates: list[ContextCandidate] = []
        for contributor in tuple(getattr(registry, "contributors", ())):
            contributor_name = str(getattr(contributor, "name", "")).strip()
            if contributor_name == "":
                continue
            if policy.contributor_allow and contributor_name not in policy.contributor_allow:
                continue
            if contributor_name in policy.contributor_deny:
                continue
            try:
                collected = await contributor.collect(
                    request,
                    policy=policy,
                    state=state,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._logging_gateway.warning(
                    "Context contributor failed "
                    f"(contributor={contributor_name} error={type(exc).__name__}: {exc})."
                )
                continue
            for candidate in collected or []:
                if isinstance(candidate, ContextCandidate):
                    candidates.append(candidate)
        return self._deduplicate_candidates(candidates)

    async def _apply_guards(
        self,
        *,
        registry: Any,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        guarded = list(candidates)
        dropped: list[ContextCandidate] = []
        for guard in tuple(getattr(registry, "guards", ())):
            before_guard = {
                candidate.artifact.artifact_id: candidate for candidate in guarded
            }
            guarded = await guard.apply(
                request,
                guarded,
                policy=policy,
                state=state,
            )
            after_ids = {
                candidate.artifact.artifact_id
                for candidate in guarded
                if isinstance(candidate, ContextCandidate)
            }
            for artifact_id, candidate in before_guard.items():
                if artifact_id in after_ids:
                    continue
                dropped.append(
                    self._with_reason(
                        candidate,
                        reason=ContextSelectionReason.DROPPED_GUARD,
                        selected=False,
                        detail=getattr(guard, "name", type(guard).__name__),
                    )
                )
            guarded = [
                candidate
                for candidate in guarded
                if isinstance(candidate, ContextCandidate)
            ]
        return guarded, dropped

    async def _apply_rankers(
        self,
        *,
        registry: Any,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        ranked = list(candidates)
        for ranker in tuple(getattr(registry, "rankers", ())):
            ranked = await ranker.rank(
                request,
                ranked,
                policy=policy,
                state=state,
            )
        return ranked

    def _select_candidates(
        self,
        *,
        candidates: list[ContextCandidate],
        policy: ContextPolicy,
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        budget = policy.budget
        sorted_candidates = sorted(
            candidates,
            key=self._candidate_sort_key,
        )
        selected: list[ContextCandidate] = []
        dropped: list[ContextCandidate] = []
        consumed_tokens = 0
        evidence_count = 0

        for candidate in sorted_candidates:
            artifact = candidate.artifact
            estimated_tokens = max(int(artifact.estimated_token_cost or 0), 1)
            if artifact.lane == "evidence":
                if evidence_count >= budget.max_evidence_items:
                    dropped.append(
                        self._with_reason(
                            candidate,
                            reason=ContextSelectionReason.DROPPED_BUDGET,
                            selected=False,
                            detail="max_evidence_items",
                        )
                    )
                    continue
            if len(selected) >= budget.max_selected_artifacts:
                dropped.append(
                    self._with_reason(
                        candidate,
                        reason=ContextSelectionReason.DROPPED_BUDGET,
                        selected=False,
                        detail="max_selected_artifacts",
                    )
                )
                continue
            if consumed_tokens + estimated_tokens > budget.max_total_tokens:
                dropped.append(
                    self._with_reason(
                        candidate,
                        reason=ContextSelectionReason.DROPPED_BUDGET,
                        selected=False,
                        detail="max_total_tokens",
                    )
                )
                continue

            consumed_tokens += estimated_tokens
            if artifact.lane == "evidence":
                evidence_count += 1
            selected.append(
                self._with_reason(
                    candidate,
                    reason=ContextSelectionReason.SELECTED,
                    selected=True,
                )
            )

        return selected, dropped

    @classmethod
    def _candidate_sort_key(cls, candidate: ContextCandidate) -> tuple[int, float, int]:
        lane_priority = cls._lane_priority.get(candidate.artifact.lane, 99)
        score = float(candidate.score if candidate.score is not None else 0.0)
        priority = int(candidate.priority)
        return (lane_priority, -score, -priority)

    @staticmethod
    def _with_reason(
        candidate: ContextCandidate,
        *,
        reason: ContextSelectionReason,
        selected: bool,
        detail: str | None = None,
    ) -> ContextCandidate:
        return ContextCandidate(
            artifact=candidate.artifact,
            contributor=candidate.contributor,
            priority=candidate.priority,
            score=candidate.score,
            selected=selected,
            selection_reason=reason,
            reason_detail=detail,
            metadata=dict(candidate.metadata),
        )

    @staticmethod
    def _deduplicate_candidates(
        candidates: list[ContextCandidate],
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        deduped: dict[tuple[str, str], ContextCandidate] = {}
        dropped: list[ContextCandidate] = []
        for candidate in candidates:
            key = (
                candidate.artifact.artifact_id,
                candidate.artifact.provenance.source_kind,
            )
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = candidate
                continue
            existing_score = float(existing.score if existing.score is not None else 0.0)
            candidate_score = float(
                candidate.score if candidate.score is not None else 0.0
            )
            if candidate_score > existing_score:
                dropped.append(
                    DefaultContextEngine._with_reason(
                        existing,
                        reason=ContextSelectionReason.DROPPED_DUPLICATE,
                        selected=False,
                        detail="replaced_by_higher_score",
                    )
                )
                deduped[key] = candidate
                continue
            dropped.append(
                DefaultContextEngine._with_reason(
                    candidate,
                    reason=ContextSelectionReason.DROPPED_DUPLICATE,
                    selected=False,
                    detail="duplicate_candidate",
                )
            )
        return list(deduped.values()), dropped

    @staticmethod
    def _state_payload(state: ContextState | None) -> dict[str, Any] | None:
        if state is None:
            return None
        return {
            "context_lane": "bounded_control_state",
            "current_objective": state.current_objective,
            "entities": dict(state.entities),
            "constraints": list(state.constraints),
            "unresolved_slots": list(state.unresolved_slots),
            "commitments": list(state.commitments),
            "safety_flags": list(state.safety_flags),
            "routing": dict(state.routing),
            "summary": state.summary,
            "revision": state.revision,
        }

    @staticmethod
    def _lane_payload(
        selected_candidates: list[ContextCandidate],
        *,
        lane: str,
    ) -> dict[str, Any] | None:
        items = [
            {
                "artifact_id": candidate.artifact.artifact_id,
                "kind": candidate.artifact.kind,
                "title": candidate.artifact.title,
                "summary": candidate.artifact.summary,
                "content": candidate.artifact.content,
                "provenance": {
                    "contributor": candidate.artifact.provenance.contributor,
                    "source_kind": candidate.artifact.provenance.source_kind,
                    "source_id": candidate.artifact.provenance.source_id,
                    "title": candidate.artifact.provenance.title,
                    "uri": candidate.artifact.provenance.uri,
                    "tenant_id": candidate.artifact.provenance.tenant_id,
                },
            }
            for candidate in selected_candidates
            if candidate.artifact.lane == lane
        ]
        if not items:
            return None
        return {
            "context_lane": lane,
            "items": items,
        }

    @staticmethod
    def _recent_turn_messages(
        selected_candidates: list[ContextCandidate],
    ) -> list[CompletionMessage]:
        messages: list[CompletionMessage] = []
        for candidate in selected_candidates:
            if candidate.artifact.lane != "recent_turn":
                continue
            content = candidate.artifact.content
            if not isinstance(content, dict):
                continue
            role = content.get("role")
            if not isinstance(role, str):
                continue
            messages.append(
                CompletionMessage(
                    role=role,
                    content=content.get("content"),
                )
            )
        return messages

    @staticmethod
    def _user_message_payload(request: ContextTurnRequest) -> Any:
        if not (
            request.message_context
            or request.attachment_context
            or request.ingress_metadata
        ):
            return request.user_message
        return {
            "message": request.user_message,
            "message_context": list(request.message_context),
            "attachment_context": list(request.attachment_context),
            "ingress_metadata": dict(request.ingress_metadata),
        }

    @staticmethod
    def _serialize_candidates(candidates: list[ContextCandidate]) -> list[dict[str, Any]]:
        return [
            {
                "artifact_id": candidate.artifact.artifact_id,
                "lane": candidate.artifact.lane,
                "kind": candidate.artifact.kind,
                "content": candidate.artifact.content,
                "contributor": candidate.contributor,
            }
            for candidate in candidates
        ]

    def _prefix_fingerprint(self, request: CompletionRequest) -> str:
        return messages_fingerprint(request.messages[:-1])

    def _commit_token(self, request: ContextTurnRequest, prefix_fingerprint: str) -> str:
        payload = {
            "scope": scope_key(request.scope),
            "message_id": request.message_id,
            "trace_id": request.trace_id,
            "prefix_fingerprint": prefix_fingerprint,
        }
        return messages_fingerprint(
            [CompletionMessage(role="system", content=payload)]
        )

    def _validate_commit_token(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
    ) -> None:
        prefix_fingerprint = prepared.bundle.prefix_fingerprint
        if prefix_fingerprint is None:
            prefix_fingerprint = self._prefix_fingerprint(prepared.completion_request)
        expected = self._commit_token(request, prefix_fingerprint)
        if prepared.commit_token != expected:
            raise RuntimeError("Invalid context commit token.")

    @staticmethod
    def _build_prepare_trace(
        *,
        request: ContextTurnRequest,
        selected_candidates: list[ContextCandidate],
        dropped_candidates: list[ContextCandidate],
    ) -> dict[str, Any]:
        return {
            "scope": scope_identity(request.scope),
            "selected": [
                {
                    "artifact_id": candidate.artifact.artifact_id,
                    "lane": candidate.artifact.lane,
                    "reason": candidate.selection_reason.value
                    if candidate.selection_reason is not None
                    else None,
                }
                for candidate in selected_candidates
            ],
            "dropped": [
                {
                    "artifact_id": candidate.artifact.artifact_id,
                    "lane": candidate.artifact.lane,
                    "reason": candidate.selection_reason.value
                    if candidate.selection_reason is not None
                    else None,
                    "detail": candidate.reason_detail,
                }
                for candidate in dropped_candidates
            ],
        }

    @staticmethod
    def _get_policy_resolver(registry: Any) -> IContextPolicyResolver:
        resolver = getattr(registry, "policy_resolver", None)
        if resolver is None:
            raise RuntimeError("Context component registry missing policy_resolver.")
        return resolver

    @staticmethod
    def _get_state_store(registry: Any) -> IContextStateStore:
        state_store = getattr(registry, "state_store", None)
        if state_store is None:
            raise RuntimeError("Context component registry missing state_store.")
        return state_store

    @staticmethod
    def _get_optional_cache(registry: Any) -> IContextCache | None:
        cache = getattr(registry, "cache", None)
        if cache is None:
            return None
        return cache

    async def _record_prepare(
        self,
        *,
        registry: Any,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        trace_enabled: bool,
    ) -> None:
        if trace_enabled is not True:
            return
        for sink in tuple(getattr(registry, "trace_sinks", ())):
            await sink.record_prepare(request=request, prepared=prepared)

    async def _record_commit(
        self,
        *,
        registry: Any,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
        result: ContextCommitResult,
        trace_enabled: bool,
    ) -> None:
        if trace_enabled is not True:
            return
        trace_sinks = tuple(getattr(registry, "trace_sinks", ()))
        for sink in trace_sinks:
            if not isinstance(sink, IContextTraceSink):
                continue
            await sink.record_commit(
                request=request,
                prepared=prepared,
                completion=completion,
                final_user_responses=final_user_responses,
                outcome=outcome,
                result=result,
            )
