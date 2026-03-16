"""Default context-engine implementation."""

from __future__ import annotations

__all__ = ["DefaultContextEngine"]

from collections import defaultdict
from dataclasses import asdict, replace
import hashlib
import json
from types import SimpleNamespace
from typing import Any

from mugen.core import di
from mugen.core.contract.context import (
    ContextBudget,
    ContextBundle,
    ContextCandidate,
    ContextCommitResult,
    ContextGuardResult,
    ContextLaneBudget,
    ContextPolicy,
    ContextSelectionReason,
    ContextSourcePolicyEffect,
    ContextSourceRef,
    ContextSourceRule,
    ContextTurnRequest,
    IContextArtifactRenderer,
    IContextCache,
    IContextCommitStore,
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
    return di.container.get_required_ext_service(
        di.EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY
    )


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


class DefaultContextEngine(IContextEngine):
    """Default provider-neutral context runtime implementation."""

    _lane_priority = {
        "system_persona_policy": 0,
        "bounded_control_state": 1,
        "operational_overlay": 2,
        "recent_turn": 3,
        "evidence": 4,
    }

    _default_render_class = {
        "system_persona_policy": "system_persona_policy_items",
        "bounded_control_state": "bounded_control_state_items",
        "operational_overlay": "operational_overlay_items",
        "recent_turn": "recent_turn_messages",
        "evidence": "evidence_items",
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
        commit_store = self._get_commit_store(registry)

        policy = await policy_resolver.resolve_policy(request)
        state = await state_store.load(request)
        effective_policy = self._effective_policy(policy=policy, request=request)

        candidates, dropped_candidates = await self._collect_candidates(
            registry=registry,
            request=request,
            policy=effective_policy,
            state=state,
        )
        source_candidates, source_dropped = self._apply_source_policy(
            request=request,
            candidates=candidates,
            policy=effective_policy,
        )
        dropped_candidates.extend(source_dropped)
        guarded_candidates, guard_dropped = await self._apply_guards(
            registry=registry,
            request=request,
            candidates=source_candidates,
            policy=effective_policy,
            state=state,
        )
        dropped_candidates.extend(guard_dropped)
        ranked_candidates = await self._apply_rankers(
            registry=registry,
            request=request,
            candidates=guarded_candidates,
            policy=effective_policy,
            state=state,
        )
        deduped_candidates, dedupe_dropped = self._deduplicate_candidates(
            ranked_candidates
        )
        dropped_candidates.extend(dedupe_dropped)
        selected_candidates, selection_dropped = self._select_candidates(
            request=request,
            candidates=deduped_candidates,
            policy=effective_policy,
        )
        dropped_candidates.extend(selection_dropped)
        completion_request = await self._compile_completion_request(
            registry=registry,
            request=request,
            policy=effective_policy,
            selected_candidates=selected_candidates,
        )
        prefix_fingerprint = self._prefix_fingerprint(completion_request)
        prepared_fingerprint = self._prepared_fingerprint(completion_request)
        commit_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint=prepared_fingerprint,
            ttl_seconds=effective_policy.retention.commit_token_ttl_seconds,
        )
        cache_hints = {
            "prefix_fingerprint": prefix_fingerprint,
            "prepared_fingerprint": prepared_fingerprint,
            "selected_artifact_ids": [
                candidate.artifact.artifact_id for candidate in selected_candidates
            ],
        }
        bundle = ContextBundle(
            policy=effective_policy,
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
            commit_token=commit_token,
            trace=dict(bundle.trace),
        )

        cache = self._get_optional_cache(registry)
        if effective_policy.cache_enabled and cache is not None:
            try:
                await cache.put(
                    namespace="retrieval",
                    key=retrieval_cache_key(request),
                    value=self._serialize_candidates(selected_candidates),
                    ttl_seconds=effective_policy.retention.cache_ttl_seconds,
                )
                await cache.put(
                    namespace="prefix_fingerprint",
                    key=prefix_cache_key(request.scope, prefix_fingerprint),
                    value={
                        "prefix_fingerprint": prefix_fingerprint,
                        "prepared_fingerprint": prepared_fingerprint,
                    },
                    ttl_seconds=effective_policy.retention.cache_ttl_seconds,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._logging_gateway.warning(
                    "Context prepare cache update failed "
                    f"(error={type(exc).__name__}: {exc})."
                )

        await self._record_prepare(
            registry=registry,
            request=request,
            prepared=prepared,
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
        commit_store = self._get_commit_store(registry)
        prepared_fingerprint = self._prepared_fingerprint(prepared.completion_request)
        commit_check = await commit_store.begin_commit(
            request=request,
            prepared=prepared,
            prepared_fingerprint=prepared_fingerprint,
        )
        if commit_check.replay_result is not None:
            return commit_check.replay_result

        warnings: list[str] = []
        try:
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
                try:
                    await cache.put(
                        namespace="working_set",
                        key=working_set_key,
                        value={
                            "state_revision": state.revision,
                            "prefix_fingerprint": prepared.bundle.prefix_fingerprint,
                            "prepared_fingerprint": prepared_fingerprint,
                        },
                        ttl_seconds=prepared.bundle.policy.retention.cache_ttl_seconds,
                    )
                    cache_updates["working_set"] = working_set_key
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    warning = f"cache_update_failed:{type(exc).__name__}"
                    warnings.append(warning)
                    self._logging_gateway.warning(
                        "Context commit cache update failed "
                        f"(error={type(exc).__name__}: {exc})."
                    )

            result = ContextCommitResult(
                commit_token=prepared.commit_token,
                state_revision=state.revision,
                memory_writes=tuple(memory_writes),
                cache_updates=cache_updates,
                warnings=tuple(warnings),
            )
            await commit_store.complete_commit(
                request=request,
                prepared=prepared,
                prepared_fingerprint=prepared_fingerprint,
                result=result,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await commit_store.fail_commit(
                request=request,
                prepared=prepared,
                prepared_fingerprint=prepared_fingerprint,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise

        try:
            await self._record_commit(
                registry=registry,
                request=request,
                prepared=prepared,
                completion=completion,
                final_user_responses=final_user_responses,
                outcome=outcome,
                result=result,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Context commit trace recording failed "
                f"(error={type(exc).__name__}: {exc})."
            )
        return result

    async def _compile_completion_request(
        self,
        *,
        registry: Any,
        request: ContextTurnRequest,
        policy: ContextPolicy,
        selected_candidates: list[ContextCandidate],
    ) -> CompletionRequest:
        messages: list[CompletionMessage] = []
        renderer_map = self._renderer_map(registry)
        grouped_candidates: dict[str, list[ContextCandidate]] = {}
        render_order: list[str] = []

        for candidate in selected_candidates:
            render_class = self._render_class(candidate)
            if render_class not in grouped_candidates:
                grouped_candidates[render_class] = []
                render_order.append(render_class)
            grouped_candidates[render_class].append(candidate)

        for render_class in render_order:
            renderer = renderer_map.get(render_class)
            if renderer is None:
                raise RuntimeError(
                    "Context renderer not registered for "
                    f"render_class={render_class!r}."
                )
            rendered = await renderer.render(
                request,
                grouped_candidates[render_class],
                policy=policy,
            )
            for message in rendered:
                if isinstance(message, CompletionMessage):
                    messages.append(message)

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
        state,
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        candidates: list[ContextCandidate] = []
        for contributor in tuple(getattr(registry, "contributors", ())):
            contributor_name = str(getattr(contributor, "name", "")).strip()
            if contributor_name == "":
                continue
            if (
                policy.contributor_allow
                and contributor_name not in policy.contributor_allow
            ):
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
                    "("
                    f"contributor={contributor_name} "
                    f"error={type(exc).__name__}: {exc}"
                    ")."
                )
                continue
            for candidate in collected or []:
                if isinstance(candidate, ContextCandidate):
                    candidates.append(candidate)
        return candidates, []

    def _apply_source_policy(
        self,
        *,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        policy: ContextPolicy,
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        rules = self._policy_source_rules(policy)
        if not rules:
            return list(candidates), []

        allow_rules = [
            rule for rule in rules if rule.effect is ContextSourcePolicyEffect.ALLOW
        ]
        deny_rules = [
            rule for rule in rules if rule.effect is ContextSourcePolicyEffect.DENY
        ]
        kept: list[ContextCandidate] = []
        dropped: list[ContextCandidate] = []

        for candidate in candidates:
            source_ref = self._candidate_source_ref(candidate)
            if source_ref is None:
                source_kind = str(
                    candidate.artifact.provenance.source_kind or ""
                ).strip()
            else:
                source_kind = source_ref.kind

            denied_by = next(
                (
                    rule
                    for rule in deny_rules
                    if rule.matches(source_ref, source_kind=source_kind)
                ),
                None,
            )
            if denied_by is not None:
                dropped.append(
                    self._with_reason(
                        candidate,
                        reason=ContextSelectionReason.DROPPED_SOURCE_POLICY,
                        selected=False,
                        detail="source_deny",
                        metadata_update={
                            "source_policy": {
                                "effect": "deny",
                                "rule": denied_by.descriptor(),
                            }
                        },
                    )
                )
                continue

            if allow_rules:
                allowed_by = next(
                    (
                        rule
                        for rule in allow_rules
                        if rule.matches(source_ref, source_kind=source_kind)
                    ),
                    None,
                )
                if allowed_by is None:
                    detail = "source_allow"
                    if source_ref is None and any(
                        rule.requires_source_ref()
                        and (rule.kind in (None, source_kind))
                        for rule in allow_rules
                    ):
                        detail = "missing_source_ref"
                    dropped.append(
                        self._with_reason(
                            candidate,
                            reason=ContextSelectionReason.DROPPED_SOURCE_POLICY,
                            selected=False,
                            detail=detail,
                            metadata_update={
                                "source_policy": {
                                    "effect": "allow",
                                    "source_kind": source_kind or None,
                                }
                            },
                        )
                    )
                    continue

            kept.append(candidate)
        return kept, dropped

    async def _apply_guards(
        self,
        *,
        registry: Any,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        policy: ContextPolicy,
        state,
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        guarded = list(candidates)
        dropped: list[ContextCandidate] = []
        for guard in tuple(getattr(registry, "guards", ())):
            before_guard = {
                candidate.artifact.artifact_id: candidate for candidate in guarded
            }
            guard_result = await guard.apply(
                request,
                guarded,
                policy=policy,
                state=state,
            )
            if isinstance(guard_result, ContextGuardResult):
                guarded = [
                    candidate
                    for candidate in guard_result.passed_candidates
                    if isinstance(candidate, ContextCandidate)
                ]
                for candidate in guard_result.dropped_candidates:
                    if not isinstance(candidate, ContextCandidate):
                        continue
                    dropped.append(
                        self._with_reason(
                            candidate,
                            reason=(
                                candidate.selection_reason
                                or ContextSelectionReason.DROPPED_GUARD
                            ),
                            selected=False,
                            detail=(
                                candidate.reason_detail
                                or getattr(guard, "name", type(guard).__name__)
                            ),
                        )
                    )
                continue

            if not isinstance(guard_result, list):
                guarded = []
                continue

            explicit_dropped: list[ContextCandidate] = []
            next_guarded: list[ContextCandidate] = []
            for candidate in guard_result:
                if not isinstance(candidate, ContextCandidate):
                    continue
                if candidate.selected is False and candidate.selection_reason in {
                    ContextSelectionReason.DROPPED_GUARD,
                    ContextSelectionReason.DROPPED_POLICY,
                    ContextSelectionReason.DROPPED_SOURCE_POLICY,
                    ContextSelectionReason.DROPPED_TENANT_MISMATCH,
                }:
                    explicit_dropped.append(candidate)
                    continue
                next_guarded.append(candidate)

            after_ids = {candidate.artifact.artifact_id for candidate in next_guarded}
            explicit_drop_ids = {
                candidate.artifact.artifact_id for candidate in explicit_dropped
            }
            for artifact_id, candidate in before_guard.items():
                if artifact_id in after_ids or artifact_id in explicit_drop_ids:
                    continue
                dropped.append(
                    self._with_reason(
                        candidate,
                        reason=ContextSelectionReason.DROPPED_GUARD,
                        selected=False,
                        detail=getattr(guard, "name", type(guard).__name__),
                    )
                )
            for candidate in explicit_dropped:
                dropped.append(
                    self._with_reason(
                        candidate,
                        reason=(
                            candidate.selection_reason
                            or ContextSelectionReason.DROPPED_GUARD
                        ),
                        selected=False,
                        detail=(
                            candidate.reason_detail
                            or getattr(guard, "name", type(guard).__name__)
                        ),
                    )
                )
            guarded = next_guarded
        return guarded, dropped

    async def _apply_rankers(
        self,
        *,
        registry: Any,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        policy: ContextPolicy,
        state,
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
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        policy: ContextPolicy,
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        budget = policy.budget
        lane_budgets = self._lane_budget_map(budget)
        sorted_candidates = sorted(candidates, key=self._candidate_sort_key)
        selected: list[ContextCandidate] = []
        dropped: list[ContextCandidate] = []
        selected_ids: set[str] = set()
        lane_counts: dict[str, int] = defaultdict(int)
        lane_tokens: dict[str, int] = defaultdict(int)
        consumed_tokens = 0

        for lane_budget in sorted(
            lane_budgets.values(),
            key=lambda item: self._lane_priority.get(item.lane, 99),
        ):
            if lane_budget.min_items <= 0:
                continue
            for candidate in sorted_candidates:
                artifact_id = candidate.artifact.artifact_id
                if artifact_id in selected_ids:
                    continue
                if candidate.artifact.lane != lane_budget.lane:
                    continue
                if lane_counts[lane_budget.lane] >= lane_budget.min_items:
                    break
                drop_detail = self._selection_drop_detail(
                    candidate=candidate,
                    budget=budget,
                    lane_budgets=lane_budgets,
                    lane_counts=lane_counts,
                    lane_tokens=lane_tokens,
                    selected_count=len(selected),
                    consumed_tokens=consumed_tokens,
                    sorted_candidates=sorted_candidates,
                    selected_ids=selected_ids,
                    apply_soft_limit=False,
                )
                if drop_detail is not None:
                    dropped.append(
                        self._with_reason(
                            candidate,
                            reason=ContextSelectionReason.DROPPED_BUDGET,
                            selected=False,
                            detail=drop_detail,
                        )
                    )
                    selected_ids.add(artifact_id)
                    continue
                selected_candidate = self._with_reason(
                    candidate,
                    reason=ContextSelectionReason.SELECTED,
                    selected=True,
                    metadata_update={"selection": {"phase": "lane_minimum"}},
                )
                selected.append(selected_candidate)
                selected_ids.add(artifact_id)
                lane_counts[candidate.artifact.lane] += 1
                estimated_tokens = max(
                    int(candidate.artifact.estimated_token_cost or 0), 1
                )
                lane_tokens[candidate.artifact.lane] += estimated_tokens
                consumed_tokens += estimated_tokens

        for candidate in sorted_candidates:
            artifact_id = candidate.artifact.artifact_id
            if artifact_id in selected_ids:
                continue
            lane_budget = lane_budgets.get(candidate.artifact.lane)
            if (
                lane_budget is not None
                and lane_budget.allow_spillover is not True
                and lane_counts[candidate.artifact.lane] >= lane_budget.min_items
            ):
                dropped.append(
                    self._with_reason(
                        candidate,
                        reason=ContextSelectionReason.DROPPED_BUDGET,
                        selected=False,
                        detail="lane_spillover_disabled",
                    )
                )
                continue
            drop_detail = self._selection_drop_detail(
                candidate=candidate,
                budget=budget,
                lane_budgets=lane_budgets,
                lane_counts=lane_counts,
                lane_tokens=lane_tokens,
                selected_count=len(selected),
                consumed_tokens=consumed_tokens,
                sorted_candidates=sorted_candidates,
                selected_ids=selected_ids,
                apply_soft_limit=True,
            )
            if drop_detail is not None:
                dropped.append(
                    self._with_reason(
                        candidate,
                        reason=ContextSelectionReason.DROPPED_BUDGET,
                        selected=False,
                        detail=drop_detail,
                    )
                )
                continue
            selected_candidate = self._with_reason(
                candidate,
                reason=ContextSelectionReason.SELECTED,
                selected=True,
                metadata_update={"selection": {"phase": "spillover"}},
            )
            selected.append(selected_candidate)
            selected_ids.add(artifact_id)
            lane_counts[candidate.artifact.lane] += 1
            estimated_tokens = max(int(candidate.artifact.estimated_token_cost or 0), 1)
            lane_tokens[candidate.artifact.lane] += estimated_tokens
            consumed_tokens += estimated_tokens

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
        metadata_update: dict[str, Any] | None = None,
    ) -> ContextCandidate:
        metadata = dict(candidate.metadata)
        if isinstance(metadata_update, dict):
            metadata.update(metadata_update)
        return ContextCandidate(
            artifact=candidate.artifact,
            contributor=candidate.contributor,
            priority=candidate.priority,
            score=candidate.score,
            selected=selected,
            selection_reason=reason,
            reason_detail=detail,
            metadata=metadata,
        )

    def _deduplicate_candidates(
        self,
        candidates: list[ContextCandidate],
    ) -> tuple[list[ContextCandidate], list[ContextCandidate]]:
        deduped: dict[str, ContextCandidate] = {}
        dropped: list[ContextCandidate] = []
        for candidate in sorted(candidates, key=self._candidate_sort_key):
            dedupe_key = self._candidate_dedupe_key(candidate)
            existing = deduped.get(dedupe_key)
            if existing is None:
                deduped[dedupe_key] = candidate
                continue
            dropped.append(
                self._with_reason(
                    candidate,
                    reason=ContextSelectionReason.DROPPED_DUPLICATE,
                    selected=False,
                    detail="duplicate_source_artifact",
                    metadata_update={
                        "dedupe": {
                            "group": dedupe_key,
                            "winner_artifact_id": existing.artifact.artifact_id,
                            "winner_contributor": existing.contributor,
                        }
                    },
                )
            )
        return list(deduped.values()), dropped

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

    def _serialize_candidates(
        self, candidates: list[ContextCandidate]
    ) -> list[dict[str, Any]]:
        return [self._candidate_trace_item(candidate) for candidate in candidates]

    def _prefix_fingerprint(self, request: CompletionRequest) -> str:
        return messages_fingerprint(request.messages[:-1])

    @staticmethod
    def _prepared_fingerprint(request: CompletionRequest) -> str:
        return _hash_payload(asdict(request))

    @classmethod
    def _render_class(cls, candidate: ContextCandidate) -> str:
        render_class = candidate.artifact.render_class
        if isinstance(render_class, str) and render_class.strip() != "":
            return render_class.strip()
        fallback = cls._default_render_class.get(candidate.artifact.lane)
        if fallback is None:
            raise RuntimeError(
                "Context artifact is missing render_class for unknown lane "
                f"{candidate.artifact.lane!r}."
            )
        return fallback

    @classmethod
    def _candidate_source_ref(
        cls, candidate: ContextCandidate
    ) -> ContextSourceRef | None:
        provenance = candidate.artifact.provenance
        if provenance.source is not None:
            return provenance.source
        source_kind = str(provenance.source_kind or "").strip()
        if source_kind == "":
            return None
        metadata = dict(provenance.metadata or {})
        source_key = metadata.get("source_key")
        if not isinstance(source_key, str) or source_key.strip() == "":
            source_key = provenance.source_id
        return ContextSourceRef(
            kind=source_kind,
            source_key=source_key,
            source_id=provenance.source_id,
            canonical_locator=(
                provenance.uri
                if isinstance(provenance.uri, str) and provenance.uri.strip() != ""
                else metadata.get("canonical_locator")
            ),
            segment_id=metadata.get("segment_id"),
            locale=metadata.get("locale"),
            category=metadata.get("category"),
        )

    @classmethod
    def _candidate_dedupe_key(cls, candidate: ContextCandidate) -> str:
        artifact = candidate.artifact
        source_ref = cls._candidate_source_ref(candidate)
        source_identity = None if source_ref is None else source_ref.identity_payload()
        content_fingerprint = _hash_payload(
            {
                "kind": artifact.kind,
                "content": artifact.content,
                "summary": artifact.summary,
                "title": artifact.title,
            }
        )
        return _hash_payload(
            {
                "lane": artifact.lane,
                "render_class": cls._render_class(candidate),
                "source_group": source_identity,
                "content_group": (
                    None if source_identity is not None else content_fingerprint
                ),
            }
        )

    @classmethod
    def _policy_source_rules(cls, policy: ContextPolicy):
        rules = list(policy.source_rules)
        for source_kind in policy.source_allow:
            rules.append(
                ContextSourceRule(
                    effect=ContextSourcePolicyEffect.ALLOW, kind=source_kind
                )
            )
        for source_kind in policy.source_deny:
            rules.append(
                ContextSourceRule(
                    effect=ContextSourcePolicyEffect.DENY, kind=source_kind
                )
            )
        return tuple(rules)

    @classmethod
    def _lane_budget_map(cls, budget: ContextBudget) -> dict[str, ContextLaneBudget]:
        lane_budgets: dict[str, ContextLaneBudget] = {
            "system_persona_policy": ContextLaneBudget(lane="system_persona_policy"),
            "bounded_control_state": ContextLaneBudget(
                lane="bounded_control_state",
                max_items=1,
            ),
            "operational_overlay": ContextLaneBudget(lane="operational_overlay"),
            "recent_turn": ContextLaneBudget(
                lane="recent_turn",
                max_items=budget.max_recent_turns,
            ),
            "evidence": ContextLaneBudget(
                lane="evidence",
                max_items=budget.max_evidence_items,
            ),
        }
        for lane_budget in budget.lane_budgets:
            existing = lane_budgets.get(lane_budget.lane)
            if existing is None:
                lane_budgets[lane_budget.lane] = lane_budget
                continue
            lane_budgets[lane_budget.lane] = ContextLaneBudget(
                lane=lane_budget.lane,
                min_items=lane_budget.min_items,
                max_items=(
                    lane_budget.max_items
                    if lane_budget.max_items is not None
                    else existing.max_items
                ),
                reserved_tokens=lane_budget.reserved_tokens,
                allow_spillover=lane_budget.allow_spillover,
            )
        return lane_budgets

    @classmethod
    def _selection_drop_detail(
        cls,
        *,
        candidate: ContextCandidate,
        budget: ContextBudget,
        lane_budgets: dict[str, ContextLaneBudget],
        lane_counts: dict[str, int],
        lane_tokens: dict[str, int],
        selected_count: int,
        consumed_tokens: int,
        sorted_candidates: list[ContextCandidate],
        selected_ids: set[str],
        apply_soft_limit: bool,
    ) -> str | None:
        artifact = candidate.artifact
        estimated_tokens = max(int(artifact.estimated_token_cost or 0), 1)
        lane_budget = lane_budgets.get(artifact.lane)
        if lane_budget is not None and lane_budget.max_items is not None:
            if lane_counts[artifact.lane] >= lane_budget.max_items:
                return f"lane_max_items:{artifact.lane}"
        if selected_count >= budget.max_selected_artifacts:
            return "max_selected_artifacts"
        reserved_tokens_remaining = cls._reserved_tokens_remaining(
            candidate_lane=artifact.lane,
            lane_budgets=lane_budgets,
            lane_tokens=lane_tokens,
            sorted_candidates=sorted_candidates,
            selected_ids=selected_ids,
        )
        projected_tokens = consumed_tokens + estimated_tokens
        if projected_tokens + reserved_tokens_remaining > budget.max_prefix_tokens:
            if reserved_tokens_remaining > 0:
                return "lane_reserved_tokens"
            return "max_prefix_tokens"
        if projected_tokens + reserved_tokens_remaining > budget.max_total_tokens:
            if reserved_tokens_remaining > 0:
                return "lane_reserved_tokens"
            return "max_total_tokens"
        soft_limit = (
            budget.soft_max_total_tokens
            if isinstance(budget.soft_max_total_tokens, int)
            and budget.soft_max_total_tokens > 0
            else budget.max_total_tokens
        )
        if (
            apply_soft_limit
            and projected_tokens + reserved_tokens_remaining > soft_limit
        ):
            return "soft_max_total_tokens"
        return None

    @classmethod
    def _reserved_tokens_remaining(
        cls,
        *,
        candidate_lane: str,
        lane_budgets: dict[str, ContextLaneBudget],
        lane_tokens: dict[str, int],
        sorted_candidates: list[ContextCandidate],
        selected_ids: set[str],
    ) -> int:
        remaining = 0
        for lane, lane_budget in lane_budgets.items():
            if lane == candidate_lane or lane_budget.reserved_tokens <= 0:
                continue
            if lane_tokens[lane] >= lane_budget.reserved_tokens:
                continue
            if not cls._lane_has_remaining_candidates(
                lane=lane,
                sorted_candidates=sorted_candidates,
                selected_ids=selected_ids,
            ):
                continue
            remaining += lane_budget.reserved_tokens - lane_tokens[lane]
        return remaining

    @staticmethod
    def _lane_has_remaining_candidates(
        *,
        lane: str,
        sorted_candidates: list[ContextCandidate],
        selected_ids: set[str],
    ) -> bool:
        for candidate in sorted_candidates:
            if candidate.artifact.lane != lane:
                continue
            if candidate.artifact.artifact_id in selected_ids:
                continue
            return True
        return False

    @staticmethod
    def _effective_policy(
        *,
        policy: ContextPolicy,
        request: ContextTurnRequest,
    ) -> ContextPolicy:
        if not request.budget_hints:
            return policy
        budget = policy.budget
        updates: dict[str, Any] = {}
        for field_name in (
            "max_total_tokens",
            "soft_max_total_tokens",
            "max_selected_artifacts",
            "max_recent_turns",
            "max_recent_messages",
            "max_evidence_items",
            "max_prefix_tokens",
        ):
            hinted = request.budget_hints.get(field_name)
            if not isinstance(hinted, int) or hinted <= 0:
                continue
            current = getattr(budget, field_name)
            if current is None or hinted < current:
                updates[field_name] = hinted
        if not updates:
            return policy
        return replace(policy, budget=replace(budget, **updates))

    @classmethod
    def _candidate_trace_item(cls, candidate: ContextCandidate) -> dict[str, Any]:
        artifact = candidate.artifact
        source_ref = cls._candidate_source_ref(candidate)
        return {
            "artifact_id": artifact.artifact_id,
            "lane": artifact.lane,
            "render_class": cls._render_class(candidate),
            "kind": artifact.kind,
            "contributor": candidate.contributor,
            "score": candidate.score,
            "priority": candidate.priority,
            "reason": (
                None
                if candidate.selection_reason is None
                else candidate.selection_reason.value
            ),
            "detail": candidate.reason_detail,
            "source": None if source_ref is None else source_ref.identity_payload(),
            "metadata": dict(candidate.metadata) if candidate.metadata else None,
        }

    @classmethod
    def _build_prepare_trace(
        cls,
        *,
        request: ContextTurnRequest,
        selected_candidates: list[ContextCandidate],
        dropped_candidates: list[ContextCandidate],
    ) -> dict[str, Any]:
        return {
            "scope": scope_identity(request.scope),
            "selected": [
                cls._candidate_trace_item(candidate)
                for candidate in selected_candidates
            ],
            "dropped": [
                cls._candidate_trace_item(candidate) for candidate in dropped_candidates
            ],
        }

    @staticmethod
    def _renderer_map(registry: Any) -> dict[str, IContextArtifactRenderer]:
        renderers = tuple(getattr(registry, "renderers", ()))
        renderer_map: dict[str, IContextArtifactRenderer] = {}
        for renderer in renderers:
            if not isinstance(renderer, IContextArtifactRenderer):
                raise RuntimeError(
                    "Context component registry contains invalid renderer."
                )
            render_class = str(renderer.render_class or "").strip()
            if render_class == "":
                raise RuntimeError("Context renderer must declare render_class.")
            renderer_map[render_class] = renderer
        return renderer_map

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
    def _get_commit_store(registry: Any) -> IContextCommitStore:
        commit_store = getattr(registry, "commit_store", None)
        if commit_store is None:
            raise RuntimeError("Context component registry missing commit_store.")
        return commit_store

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
    ) -> None:
        policy = prepared.bundle.policy
        if policy.trace_enabled is not True or policy.trace_capture_prepare is not True:
            return
        for sink in tuple(getattr(registry, "trace_sinks", ())):
            if not isinstance(sink, IContextTraceSink):
                continue
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
    ) -> None:
        policy = prepared.bundle.policy
        if policy.trace_enabled is not True or policy.trace_capture_commit is not True:
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
