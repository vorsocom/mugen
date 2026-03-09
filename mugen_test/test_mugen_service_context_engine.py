"""Unit tests for mugen.core.service.context_engine.DefaultContextEngine."""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import mugen.core.service.context_engine as context_engine_module
from mugen.core.contract.context import (
    ContextArtifact,
    ContextBundle,
    ContextBudget,
    ContextCandidate,
    ContextCommitCheck,
    ContextCommitResult,
    ContextCommitState,
    ContextGuardResult,
    ContextPolicy,
    ContextProvenance,
    ContextRetentionPolicy,
    ContextScope,
    ContextSelectionReason,
    ContextState,
    ContextSourcePolicyEffect,
    ContextSourceRef,
    ContextSourceRule,
    IContextArtifactRenderer,
    ContextTurnRequest,
    IContextTraceSink,
    MemoryWrite,
    MemoryWriteType,
    PreparedContextTurn,
)
from mugen.core.contract.context.result import TurnOutcome
from mugen.core.contract.gateway.completion import CompletionMessage, CompletionResponse
from mugen.core.service.context_engine import DefaultContextEngine
from mugen.core.utility.context_runtime import working_set_cache_key


def _scope() -> ContextScope:
    return ContextScope(
        tenant_id="tenant-1",
        platform="matrix",
        channel_id="matrix",
        room_id="room-1",
        sender_id="user-1",
        conversation_id="room-1",
    )


def _candidate(
    *,
    artifact_id: str,
    lane: str,
    content,
    contributor: str = "test",
    source_kind: str = "source",
    score: float = 0.0,
    estimated_token_cost: int = 1,
) -> ContextCandidate:
    return ContextCandidate(
        artifact=ContextArtifact(
            artifact_id=artifact_id,
            lane=lane,
            kind=lane,
            content=content,
            provenance=ContextProvenance(
                contributor=contributor,
                source_kind=source_kind,
                source_id=artifact_id,
                tenant_id="tenant-1",
            ),
            estimated_token_cost=estimated_token_cost,
        ),
        contributor=contributor,
        priority=10,
        score=score,
    )


class _PolicyResolver:
    def __init__(self, policy: ContextPolicy) -> None:
        self.calls: list[ContextTurnRequest] = []
        self._policy = policy

    async def resolve_policy(self, request: ContextTurnRequest) -> ContextPolicy:
        self.calls.append(request)
        return self._policy


class _StateStore:
    def __init__(self, state: ContextState) -> None:
        self.load_calls: list[ContextTurnRequest] = []
        self.save_calls: list[dict] = []
        self.clear_calls: list[ContextTurnRequest] = []
        self._state = state

    async def load(self, request: ContextTurnRequest) -> ContextState | None:
        self.load_calls.append(request)
        return self._state

    async def save(
        self,
        *,
        request: ContextTurnRequest,
        prepared,
        completion,
        final_user_responses,
        outcome,
    ) -> ContextState:
        self.save_calls.append(
            {
                "request": request,
                "prepared": prepared,
                "completion": completion,
                "final_user_responses": final_user_responses,
                "outcome": outcome,
            }
        )
        self._state = ContextState(
            current_objective=self._state.current_objective,
            entities=dict(self._state.entities),
            constraints=list(self._state.constraints),
            unresolved_slots=list(self._state.unresolved_slots),
            commitments=list(self._state.commitments),
            safety_flags=list(self._state.safety_flags),
            routing=dict(self._state.routing),
            summary=self._state.summary,
            revision=self._state.revision + 1,
        )
        return self._state

    async def clear(self, request: ContextTurnRequest) -> None:
        self.clear_calls.append(request)


class _Contributor:
    def __init__(self, name: str, candidates: list[ContextCandidate]) -> None:
        self._name = name
        self._candidates = candidates

    @property
    def name(self) -> str:
        return self._name

    async def collect(self, request, *, policy, state):
        _ = (request, policy, state)
        return list(self._candidates)


class _ErrorContributor:
    def __init__(self, name: str = "broken") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def collect(self, request, *, policy, state):
        _ = (request, policy, state)
        raise RuntimeError("boom")


class _InvalidItemContributor:
    def __init__(self, name: str = "invalid") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def collect(self, request, *, policy, state):
        _ = (request, policy, state)
        return ["bad-item"]


class _PassthroughGuard:
    name = "guard"

    async def apply(self, request, candidates, *, policy, state):
        _ = (request, policy, state)
        return [*candidates, "bad-item"]


class _Guard:
    def __init__(self, *, dropped_artifact_ids: set[str]) -> None:
        self._dropped_artifact_ids = dropped_artifact_ids
        self.calls: list[tuple[ContextTurnRequest, list[ContextCandidate]]] = []

    @property
    def name(self) -> str:
        return "tenant_guard"

    async def apply(self, request, candidates, *, policy, state):
        _ = (policy, state)
        self.calls.append((request, list(candidates)))
        return [
            candidate
            for candidate in candidates
            if candidate.artifact.artifact_id not in self._dropped_artifact_ids
        ]


class _Ranker:
    @property
    def name(self) -> str:
        return "score_ranker"

    async def rank(self, request, candidates, *, policy, state):
        _ = (request, policy, state)
        return sorted(
            candidates,
            key=lambda candidate: float(candidate.score or 0.0),
            reverse=True,
        )


class _MemoryWriter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def persist(
        self,
        *,
        request,
        prepared,
        completion,
        final_user_responses,
        outcome,
    ):
        self.calls.append(
            {
                "request": request,
                "prepared": prepared,
                "completion": completion,
                "final_user_responses": final_user_responses,
                "outcome": outcome,
            }
        )
        return [
            MemoryWrite(
                write_type=MemoryWriteType.SUMMARY,
                content={"summary": "saved"},
                provenance=ContextProvenance(
                    contributor="memory_writer",
                    source_kind="derived",
                    tenant_id=request.scope.tenant_id,
                ),
            )
        ]


class _Cache:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []

    async def get(self, *, namespace: str, key: str):
        _ = (namespace, key)
        return None

    async def put(self, *, namespace: str, key: str, value, ttl_seconds=None) -> None:
        self.put_calls.append(
            {
                "namespace": namespace,
                "key": key,
                "value": value,
                "ttl_seconds": ttl_seconds,
            }
        )

    async def invalidate(self, *, namespace: str, key_prefix: str) -> int:
        _ = (namespace, key_prefix)
        return 0


class _CommitStore:
    def __init__(self) -> None:
        self.issued: dict[str, dict[str, object]] = {}

    async def issue_token(
        self,
        *,
        request,
        prepared_fingerprint: str,
        ttl_seconds=None,
    ) -> str:
        _ = ttl_seconds
        token = f"commit-{len(self.issued) + 1}"
        self.issued[token] = {
            "scope_key": context_engine_module.scope_key(request.scope),
            "prepared_fingerprint": prepared_fingerprint,
            "state": ContextCommitState.PREPARED,
            "result": None,
        }
        return token

    async def begin_commit(self, *, request, prepared, prepared_fingerprint):
        row = self.issued.get(prepared.commit_token)
        if row is None:
            raise RuntimeError("Invalid context commit token.")
        if row["scope_key"] != context_engine_module.scope_key(request.scope):
            raise RuntimeError("Invalid context commit token.")
        if row["prepared_fingerprint"] != prepared_fingerprint:
            raise RuntimeError("Invalid context commit token.")
        if row["state"] is ContextCommitState.COMMITTED:
            return ContextCommitCheck(
                state=ContextCommitState.COMMITTED,
                replay_result=row["result"],
            )
        if row["state"] is ContextCommitState.FAILED:
            raise RuntimeError("Invalid context commit token.")
        row["state"] = ContextCommitState.COMMITTING
        return ContextCommitCheck(state=ContextCommitState.COMMITTING)

    async def complete_commit(self, *, request, prepared, prepared_fingerprint, result):
        _ = request
        row = self.issued.get(prepared.commit_token)
        if row is None or row["prepared_fingerprint"] != prepared_fingerprint:
            raise RuntimeError("Invalid context commit token.")
        row["state"] = ContextCommitState.COMMITTED
        row["result"] = result

    async def fail_commit(
        self, *, request, prepared, prepared_fingerprint, error_message
    ):
        _ = (request, prepared_fingerprint, error_message)
        row = self.issued.get(prepared.commit_token)
        if row is not None:
            row["state"] = ContextCommitState.FAILED


class _StructuredRenderer(IContextArtifactRenderer):
    def __init__(self, *, render_class: str, lane: str) -> None:
        self._render_class = render_class
        self._lane = lane

    @property
    def render_class(self) -> str:
        return self._render_class

    async def render(self, request, candidates, *, policy):
        _ = (request, policy)
        return [
            CompletionMessage(
                role="system",
                content={
                    "context_lane": self._lane,
                    "items": [
                        {
                            "artifact_id": candidate.artifact.artifact_id,
                            "content": candidate.artifact.content,
                        }
                        for candidate in candidates
                    ],
                },
            )
        ]


class _RecentTurnRenderer(IContextArtifactRenderer):
    render_class = "recent_turn_messages"

    async def render(self, request, candidates, *, policy):
        _ = (request, policy)
        return [
            CompletionMessage(
                role=candidate.artifact.content["role"],
                content=candidate.artifact.content["content"],
            )
            for candidate in candidates
        ]


class _TraceSink(IContextTraceSink):
    def __init__(self) -> None:
        self.prepare_calls: list[dict] = []
        self.commit_calls: list[dict] = []

    async def record_prepare(self, *, request, prepared) -> None:
        self.prepare_calls.append({"request": request, "prepared": prepared})

    async def record_commit(
        self,
        *,
        request,
        prepared,
        completion,
        final_user_responses,
        outcome,
        result,
    ) -> None:
        self.commit_calls.append(
            {
                "request": request,
                "prepared": prepared,
                "completion": completion,
                "final_user_responses": final_user_responses,
                "outcome": outcome,
                "result": result,
            }
        )


class TestDefaultContextEngine(unittest.IsolatedAsyncioTestCase):
    """Covers prepare/commit behavior of the default context runtime."""

    def _new_registry(self):
        policy = ContextPolicy(
            budget=ContextBudget(
                max_total_tokens=5,
                max_selected_artifacts=8,
                max_evidence_items=8,
            ),
            retention=ContextRetentionPolicy(cache_ttl_seconds=30),
            trace_enabled=True,
            cache_enabled=True,
        )
        state = ContextState(
            current_objective="help user",
            entities={"topic": "support"},
            revision=3,
        )
        persona = _candidate(
            artifact_id="persona-1",
            lane="system_persona_policy",
            content={"instruction": "Be concise."},
            contributor="persona",
            source_kind="config",
            score=10.0,
        )
        bounded_state = _candidate(
            artifact_id="bounded-state",
            lane="bounded_control_state",
            content={"summary": "state"},
            contributor="state",
            source_kind="state_snapshot",
            score=9.5,
        )
        overlay = _candidate(
            artifact_id="overlay-1",
            lane="operational_overlay",
            content={"work_item": "case-1"},
            contributor="orchestration",
            source_kind="ops",
            score=9.0,
        )
        recent_turn = _candidate(
            artifact_id="turn-1",
            lane="recent_turn",
            content={"role": "assistant", "content": "How can I help?"},
            contributor="recent_turns",
            source_kind="event_log",
            score=8.0,
        )
        evidence = _candidate(
            artifact_id="kb-1",
            lane="evidence",
            content={"snippet": "knowledge"},
            contributor="knowledge_pack",
            source_kind="knowledge_pack",
            score=7.0,
        )
        duplicate = _candidate(
            artifact_id="kb-1",
            lane="evidence",
            content={"snippet": "older knowledge"},
            contributor="knowledge_pack",
            source_kind="knowledge_pack",
            score=1.0,
        )
        overflow = _candidate(
            artifact_id="kb-2",
            lane="evidence",
            content={"snippet": "overflow"},
            contributor="knowledge_pack",
            source_kind="knowledge_pack",
            score=6.0,
        )
        cross_tenant = _candidate(
            artifact_id="audit-1",
            lane="evidence",
            content={"trace": "should drop"},
            contributor="audit",
            source_kind="audit",
            score=5.0,
        )

        registry = SimpleNamespace(
            policy_resolver=_PolicyResolver(policy),
            state_store=_StateStore(state),
            commit_store=_CommitStore(),
            contributors=(
                _Contributor(
                    "lane_source",
                    [
                        persona,
                        bounded_state,
                        overlay,
                        recent_turn,
                        evidence,
                        overflow,
                        cross_tenant,
                    ],
                ),
                _Contributor("dedupe_source", [duplicate]),
            ),
            guards=(_Guard(dropped_artifact_ids={"audit-1"}),),
            rankers=(_Ranker(),),
            memory_writer=_MemoryWriter(),
            cache=_Cache(),
            renderers=(
                _StructuredRenderer(
                    render_class="system_persona_policy_items",
                    lane="system_persona_policy",
                ),
                _StructuredRenderer(
                    render_class="bounded_control_state_items",
                    lane="bounded_control_state",
                ),
                _StructuredRenderer(
                    render_class="operational_overlay_items",
                    lane="operational_overlay",
                ),
                _StructuredRenderer(
                    render_class="evidence_items",
                    lane="evidence",
                ),
                _RecentTurnRenderer(),
            ),
            trace_sinks=(_TraceSink(),),
        )
        return registry

    async def test_prepare_turn_compiles_messages_and_tracks_dropped_candidates(
        self,
    ) -> None:
        registry = self._new_registry()
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        request = ContextTurnRequest(scope=_scope(), user_message="hello")

        with patch(
            "mugen.core.service.context_engine._context_component_registry_provider",
            return_value=registry,
        ):
            prepared = await engine.prepare_turn(request)

        self.assertEqual(
            [message.role for message in prepared.completion_request.messages],
            ["system", "system", "system", "assistant", "system", "user"],
        )
        self.assertEqual(
            prepared.completion_request.messages[0].content["context_lane"],
            "system_persona_policy",
        )
        self.assertEqual(
            prepared.completion_request.messages[1].content["context_lane"],
            "bounded_control_state",
        )
        self.assertEqual(
            prepared.completion_request.messages[2].content["context_lane"],
            "operational_overlay",
        )
        self.assertEqual(
            prepared.completion_request.messages[4].content["context_lane"],
            "evidence",
        )
        self.assertEqual(prepared.completion_request.messages[-1].content, "hello")

        self.assertEqual(
            [
                candidate.artifact.artifact_id
                for candidate in prepared.bundle.selected_candidates
            ],
            ["persona-1", "bounded-state", "overlay-1", "turn-1", "kb-1"],
        )
        dropped_reasons = {
            candidate.artifact.artifact_id: candidate.selection_reason
            for candidate in prepared.bundle.dropped_candidates
        }
        self.assertEqual(
            dropped_reasons["kb-1"],
            ContextSelectionReason.DROPPED_DUPLICATE,
        )
        self.assertEqual(
            dropped_reasons["audit-1"],
            ContextSelectionReason.DROPPED_GUARD,
        )
        self.assertEqual(
            dropped_reasons["kb-2"],
            ContextSelectionReason.DROPPED_BUDGET,
        )
        self.assertEqual(len(registry.cache.put_calls), 2)
        self.assertEqual(
            {call["namespace"] for call in registry.cache.put_calls},
            {"retrieval", "prefix_fingerprint"},
        )
        self.assertEqual(len(registry.trace_sinks[0].prepare_calls), 1)

    async def test_commit_turn_persists_state_memory_cache_and_trace(self) -> None:
        registry = self._new_registry()
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        request = ContextTurnRequest(scope=_scope(), user_message="hello")

        with patch(
            "mugen.core.service.context_engine._context_component_registry_provider",
            return_value=registry,
        ):
            prepared = await engine.prepare_turn(request)
            result = await engine.commit_turn(
                request=request,
                prepared=prepared,
                completion=CompletionResponse(content="assistant answer"),
                final_user_responses=[{"type": "text", "content": "assistant answer"}],
                outcome=TurnOutcome.COMPLETED,
            )

        self.assertIsInstance(result, ContextCommitResult)
        self.assertEqual(result.commit_token, prepared.commit_token)
        self.assertEqual(result.state_revision, 4)
        self.assertEqual(len(result.memory_writes), 1)
        self.assertEqual(result.memory_writes[0].write_type, MemoryWriteType.SUMMARY)
        self.assertEqual(
            result.cache_updates["working_set"], working_set_cache_key(_scope())
        )
        self.assertEqual(len(registry.state_store.save_calls), 1)
        self.assertEqual(len(registry.memory_writer.calls), 1)
        self.assertEqual(len(registry.trace_sinks[0].commit_calls), 1)
        self.assertEqual(
            registry.trace_sinks[0].commit_calls[0]["result"].state_revision,
            4,
        )

    async def test_commit_turn_rejects_invalid_commit_token(self) -> None:
        registry = self._new_registry()
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        request = ContextTurnRequest(scope=_scope(), user_message="hello")

        with patch(
            "mugen.core.service.context_engine._context_component_registry_provider",
            return_value=registry,
        ):
            prepared = await engine.prepare_turn(request)
            bad_prepared = prepared.__class__(
                completion_request=prepared.completion_request,
                bundle=prepared.bundle,
                state_handle=prepared.state_handle,
                commit_token="bad-token",
                trace=prepared.trace,
            )
            with self.assertRaisesRegex(RuntimeError, "Invalid context commit token"):
                await engine.commit_turn(
                    request=request,
                    prepared=bad_prepared,
                    completion=CompletionResponse(content="assistant answer"),
                    final_user_responses=[
                        {"type": "text", "content": "assistant answer"}
                    ],
                    outcome=TurnOutcome.COMPLETED,
                )

        self.assertEqual(registry.state_store.save_calls, [])

    def test_context_component_registry_provider_uses_di_container(self) -> None:
        registry = object()
        container = SimpleNamespace(
            get_required_ext_service=Mock(return_value=registry)
        )

        with patch.object(context_engine_module.di, "container", container):
            self.assertIs(
                context_engine_module._context_component_registry_provider(),
                registry,
            )

        container.get_required_ext_service.assert_called_once_with(
            context_engine_module.di.EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY
        )

    async def test_skip_optional_cache_memory_and_trace_when_disabled(
        self,
    ) -> None:
        policy = ContextPolicy(
            budget=ContextBudget(max_total_tokens=8, max_selected_artifacts=4),
            retention=ContextRetentionPolicy(cache_ttl_seconds=30),
            trace_enabled=False,
            cache_enabled=False,
        )
        registry = SimpleNamespace(
            policy_resolver=_PolicyResolver(policy),
            state_store=_StateStore(ContextState(revision=0)),
            commit_store=_CommitStore(),
            contributors=(),
            guards=(),
            rankers=(),
            trace_sinks=("not-a-sink",),
        )
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        request = ContextTurnRequest(
            scope=_scope(),
            user_message="hello",
            ingress_metadata={"trace": "1"},
        )

        with patch(
            "mugen.core.service.context_engine._context_component_registry_provider",
            return_value=registry,
        ):
            prepared = await engine.prepare_turn(request)
            result = await engine.commit_turn(
                request=request,
                prepared=prepared,
                completion=None,
                final_user_responses=[],
                outcome=TurnOutcome.COMPLETION_FAILED,
            )

        self.assertEqual(result.memory_writes, ())
        self.assertEqual(result.cache_updates, {})

    async def test_collect_candidates_skips_filtered_invalid_and_failing_contributors(
        self,
    ) -> None:
        logging_gateway = Mock()
        engine = DefaultContextEngine(
            config=SimpleNamespace(),
            logging_gateway=logging_gateway,
        )
        candidate = _candidate(
            artifact_id="kept",
            lane="evidence",
            content={"snippet": "ok"},
        )
        policy = ContextPolicy(
            contributor_allow=("kept",), contributor_deny=("denied",)
        )
        registry = SimpleNamespace(
            contributors=(
                _Contributor(" ", [candidate]),
                _Contributor("allowed", [candidate]),
                _Contributor("denied", [candidate]),
                _ErrorContributor("kept"),
                _InvalidItemContributor("kept"),
                _Contributor("kept", [candidate]),
            )
        )

        collected, dropped = (
            await engine._collect_candidates(  # pylint: disable=protected-access
                registry=registry,
                request=ContextTurnRequest(scope=_scope(), user_message="hello"),
                policy=policy,
                state=None,
            )
        )

        self.assertEqual([item.artifact.artifact_id for item in collected], ["kept"])
        self.assertEqual(dropped, [])
        logging_gateway.warning.assert_called_once()

        denied_only, _ = (
            await engine._collect_candidates(  # pylint: disable=protected-access
                registry=SimpleNamespace(
                    contributors=(_Contributor("denied", [candidate]),)
                ),
                request=ContextTurnRequest(scope=_scope(), user_message="hello"),
                policy=ContextPolicy(contributor_deny=("denied",)),
                state=None,
            )
        )
        self.assertEqual(denied_only, [])

    async def test_apply_guards_filters_invalid_items_and_records_drop_reason(
        self,
    ) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        candidate = _candidate(
            artifact_id="guarded",
            lane="evidence",
            content={"snippet": "ok"},
        )

        guarded, dropped = (
            await engine._apply_guards(  # pylint: disable=protected-access
                registry=SimpleNamespace(guards=(_PassthroughGuard(),)),
                request=ContextTurnRequest(scope=_scope(), user_message="hello"),
                candidates=[candidate],
                policy=ContextPolicy(),
                state=None,
            )
        )

        self.assertEqual(guarded, [candidate])
        self.assertEqual(dropped, [])

    async def test_private_helper_methods_cover_payload_sort_and_validation_paths(
        self,
    ) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        wrapped_user_payload = (
            engine._user_message_payload(  # pylint: disable=protected-access
                ContextTurnRequest(
                    scope=_scope(),
                    user_message="hello",
                    message_context=[{"type": "seed", "content": "ctx"}],
                )
            )
        )
        bare_user_payload = (
            engine._user_message_payload(  # pylint: disable=protected-access
                ContextTurnRequest(scope=_scope(), user_message="hello")
            )
        )
        recent_turn = ContextCandidate(
            artifact=ContextArtifact(
                artifact_id="recent",
                lane="recent_turn",
                kind="recent_turn",
                render_class="recent_turn_messages",
                content={"role": "assistant", "content": "ok"},
                provenance=ContextProvenance(
                    contributor="recent",
                    source_kind="event_log",
                    source=ContextSourceRef(
                        kind="event_log",
                        source_key="scope-1",
                        source_id="1",
                    ),
                    tenant_id="tenant-1",
                ),
            ),
            contributor="recent",
        )
        system_item = _candidate(
            artifact_id="persona",
            lane="system_persona_policy",
            content={"instruction": "Be concise."},
        )
        # pylint: disable=protected-access
        prepared = await engine._compile_completion_request(
            registry=SimpleNamespace(
                renderers=(
                    _StructuredRenderer(
                        render_class="system_persona_policy_items",
                        lane="system_persona_policy",
                    ),
                    _RecentTurnRenderer(),
                )
            ),
            request=ContextTurnRequest(scope=_scope(), user_message="hello"),
            policy=ContextPolicy(metadata={"policy": "strict"}),
            selected_candidates=[system_item, recent_turn],
        )
        self.assertEqual(bare_user_payload, "hello")
        self.assertEqual(wrapped_user_payload["message"], "hello")
        self.assertEqual(
            [message.role for message in prepared.messages],
            ["system", "assistant", "user"],
        )
        self.assertEqual(
            prepared.messages[0].content["context_lane"],
            "system_persona_policy",
        )
        self.assertEqual(prepared.messages[1].content, "ok")
        self.assertEqual(
            engine._candidate_sort_key(  # pylint: disable=protected-access
                _candidate(
                    artifact_id="unknown",
                    lane="custom",
                    content={"x": 1},
                    score=1.5,
                )
            ),
            (99, -1.5, -10),
        )
        self.assertEqual(
            engine._get_optional_cache(
                SimpleNamespace()
            ),  # pylint: disable=protected-access
            None,
        )
        self.assertEqual(
            engine._candidate_source_ref(
                recent_turn
            ).identity_payload(),  # pylint: disable=protected-access
            {
                "kind": "event_log",
                "source_key": "scope-1",
                "source_id": "1",
                "canonical_locator": None,
                "segment_id": None,
                "locale": None,
                "category": None,
            },
        )

        with self.assertRaisesRegex(RuntimeError, "missing policy_resolver"):
            engine._get_policy_resolver(
                SimpleNamespace()
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "missing state_store"):
            engine._get_state_store(
                SimpleNamespace()
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "missing commit_store"):
            engine._get_commit_store(
                SimpleNamespace()
            )  # pylint: disable=protected-access

        self.assertEqual(
            prepared.vendor_params["context_policy"],
            {"policy": "strict"},
        )

    def test_selection_and_dedup_cover_budget_edges(self) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        request = ContextTurnRequest(scope=_scope(), user_message="hello")
        evidence_a = _candidate(
            artifact_id="evidence-a",
            lane="evidence",
            content={"a": 1},
            estimated_token_cost=1,
            score=9.0,
        )
        evidence_b = _candidate(
            artifact_id="evidence-b",
            lane="evidence",
            content={"b": 1},
            estimated_token_cost=1,
            score=8.0,
        )
        overlay = _candidate(
            artifact_id="overlay-a",
            lane="operational_overlay",
            content={"w": 1},
            estimated_token_cost=5,
            score=7.0,
        )
        selected, dropped = (
            engine._select_candidates(  # pylint: disable=protected-access
                request=request,
                candidates=[evidence_a, evidence_b],
                policy=ContextPolicy(
                    budget=ContextBudget(
                        max_total_tokens=4,
                        max_selected_artifacts=8,
                        max_evidence_items=1,
                    )
                ),
            )
        )
        self.assertEqual(
            [item.artifact.artifact_id for item in selected], ["evidence-a"]
        )
        self.assertEqual(dropped[0].reason_detail, "lane_max_items:evidence")

        selected, dropped = (
            engine._select_candidates(  # pylint: disable=protected-access
                request=request,
                candidates=[evidence_a, overlay],
                policy=ContextPolicy(
                    budget=ContextBudget(
                        max_total_tokens=10,
                        max_selected_artifacts=1,
                        max_evidence_items=8,
                    )
                ),
            )
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(dropped[0].reason_detail, "max_selected_artifacts")

        selected, dropped = (
            engine._select_candidates(  # pylint: disable=protected-access
                request=request,
                candidates=[overlay],
                policy=ContextPolicy(
                    budget=ContextBudget(
                        max_total_tokens=1,
                        max_selected_artifacts=8,
                        max_evidence_items=8,
                    )
                ),
            )
        )
        self.assertEqual(selected, [])
        self.assertEqual(dropped[0].reason_detail, "max_total_tokens")

        deduped, dedup_dropped = (
            engine._deduplicate_candidates(  # pylint: disable=protected-access
                [
                    _candidate(
                        artifact_id="dup",
                        lane="evidence",
                        content={"old": True},
                        source_kind="knowledge",
                        score=1.0,
                    ),
                    _candidate(
                        artifact_id="dup",
                        lane="evidence",
                        content={"new": True},
                        source_kind="knowledge",
                        score=2.0,
                    ),
                ]
            )
        )
        self.assertEqual(deduped[0].artifact.content, {"new": True})
        self.assertEqual(dedup_dropped[0].reason_detail, "duplicate_source_artifact")

        source_allowed, source_dropped = (
            engine._apply_source_policy(  # pylint: disable=protected-access
                request=request,
                candidates=[
                    _candidate(
                        artifact_id="allowed",
                        lane="evidence",
                        content={"a": 1},
                        source_kind="knowledge",
                    ),
                    _candidate(
                        artifact_id="blocked",
                        lane="evidence",
                        content={"b": 1},
                        source_kind="memory",
                    ),
                ],
                policy=ContextPolicy(
                    source_rules=(
                        ContextSourceRule(
                            effect=ContextSourcePolicyEffect.ALLOW,
                            kind="knowledge",
                        ),
                        ContextSourceRule(
                            effect=ContextSourcePolicyEffect.DENY,
                            kind="memory",
                        ),
                    )
                ),
            )
        )
        self.assertEqual(
            [candidate.artifact.artifact_id for candidate in source_allowed],
            ["allowed"],
        )
        self.assertEqual(
            source_dropped[0].selection_reason,
            ContextSelectionReason.DROPPED_SOURCE_POLICY,
        )

    def test_selection_helpers_cover_lane_minimums_reservations_and_soft_budget(
        self,
    ) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        request = ContextTurnRequest(scope=_scope(), user_message="hello")
        evidence_a = _candidate(
            artifact_id="evidence-a",
            lane="evidence",
            content={"a": 1},
            estimated_token_cost=1,
            score=9.0,
        )
        evidence_b = _candidate(
            artifact_id="evidence-b",
            lane="evidence",
            content={"b": 1},
            estimated_token_cost=1,
            score=8.0,
        )
        selected, dropped = (
            engine._select_candidates(  # pylint: disable=protected-access
                request=request,
                candidates=[evidence_a, evidence_b],
                policy=ContextPolicy(
                    budget=ContextBudget(
                        max_total_tokens=10,
                        max_selected_artifacts=10,
                        lane_budgets=(
                            context_engine_module.ContextLaneBudget(
                                lane="evidence",
                                min_items=1,
                                allow_spillover=False,
                            ),
                        ),
                    )
                ),
            )
        )
        self.assertEqual(
            [item.artifact.artifact_id for item in selected], ["evidence-a"]
        )
        self.assertEqual(dropped[0].reason_detail, "lane_spillover_disabled")

        custom_budget_map = engine._lane_budget_map(  # pylint: disable=protected-access
            ContextBudget(
                lane_budgets=(
                    context_engine_module.ContextLaneBudget(
                        lane="custom_lane",
                        min_items=1,
                    ),
                )
            )
        )
        self.assertIn("custom_lane", custom_budget_map)
        merged_budget_map = engine._lane_budget_map(  # pylint: disable=protected-access
            ContextBudget(
                max_recent_turns=3,
                lane_budgets=(
                    context_engine_module.ContextLaneBudget(
                        lane="recent_turn",
                        min_items=1,
                        allow_spillover=False,
                    ),
                ),
            )
        )
        self.assertEqual(merged_budget_map["recent_turn"].min_items, 1)
        self.assertEqual(merged_budget_map["recent_turn"].max_items, 3)
        self.assertFalse(merged_budget_map["recent_turn"].allow_spillover)
        overlay = _candidate(
            artifact_id="overlay-a",
            lane="operational_overlay",
            content={"w": 1},
            estimated_token_cost=2,
            score=7.0,
        )
        selected, dropped = (
            engine._select_candidates(  # pylint: disable=protected-access
                request=request,
                candidates=[evidence_a, overlay],
                policy=ContextPolicy(
                    budget=ContextBudget(
                        max_total_tokens=10,
                        max_selected_artifacts=10,
                        max_evidence_items=8,
                        lane_budgets=(
                            context_engine_module.ContextLaneBudget(
                                lane="operational_overlay",
                                min_items=1,
                            ),
                            context_engine_module.ContextLaneBudget(
                                lane="evidence",
                                min_items=1,
                            ),
                        ),
                    )
                ),
            )
        )
        self.assertEqual(
            [item.artifact.artifact_id for item in selected],
            ["overlay-a", "evidence-a"],
        )
        self.assertEqual(dropped, [])
        lane_min_drop_selected, lane_min_drop_dropped = (
            engine._select_candidates(  # pylint: disable=protected-access
                request=request,
                candidates=[
                    _candidate(
                        artifact_id="min-drop",
                        lane="evidence",
                        content={"x": 1},
                        estimated_token_cost=2,
                    )
                ],
                policy=ContextPolicy(
                    budget=ContextBudget(
                        max_total_tokens=1,
                        max_prefix_tokens=99,
                        max_selected_artifacts=10,
                        max_evidence_items=8,
                        lane_budgets=(
                            context_engine_module.ContextLaneBudget(
                                lane="evidence",
                                min_items=1,
                            ),
                        ),
                    )
                ),
            )
        )
        self.assertEqual(lane_min_drop_selected, [])
        self.assertEqual(
            lane_min_drop_dropped[0].reason_detail,
            "max_total_tokens",
        )

        overlay = _candidate(
            artifact_id="overlay-a",
            lane="operational_overlay",
            content={"w": 1},
            estimated_token_cost=2,
            score=7.0,
        )
        recent = _candidate(
            artifact_id="recent-a",
            lane="recent_turn",
            content={"role": "assistant", "content": "hello"},
            estimated_token_cost=1,
            score=6.0,
        )
        reserved_budget = ContextBudget(
            max_total_tokens=4,
            max_prefix_tokens=4,
            lane_budgets=(
                context_engine_module.ContextLaneBudget(
                    lane="recent_turn",
                    reserved_tokens=2,
                ),
            ),
        )
        reserved_drop = (
            engine._selection_drop_detail(  # pylint: disable=protected-access
                candidate=overlay,
                budget=reserved_budget,
                lane_budgets=engine._lane_budget_map(
                    reserved_budget
                ),  # pylint: disable=protected-access
                lane_counts=defaultdict(int),
                lane_tokens=defaultdict(int),
                selected_count=0,
                consumed_tokens=1,
                sorted_candidates=[overlay, recent],
                selected_ids=set(),
                apply_soft_limit=False,
            )
        )
        self.assertEqual(reserved_drop, "lane_reserved_tokens")

        total_budget = ContextBudget(
            max_total_tokens=4,
            max_prefix_tokens=99,
            lane_budgets=(
                context_engine_module.ContextLaneBudget(
                    lane="recent_turn",
                    reserved_tokens=2,
                ),
            ),
        )
        self.assertEqual(
            engine._selection_drop_detail(  # pylint: disable=protected-access
                candidate=overlay,
                budget=total_budget,
                lane_budgets=engine._lane_budget_map(
                    total_budget
                ),  # pylint: disable=protected-access
                lane_counts=defaultdict(int),
                lane_tokens=defaultdict(int),
                selected_count=0,
                consumed_tokens=1,
                sorted_candidates=[overlay, recent],
                selected_ids=set(),
                apply_soft_limit=False,
            ),
            "lane_reserved_tokens",
        )

        soft_budget = ContextBudget(
            max_total_tokens=10,
            soft_max_total_tokens=2,
            max_prefix_tokens=10,
        )
        self.assertEqual(
            engine._selection_drop_detail(  # pylint: disable=protected-access
                candidate=evidence_a,
                budget=soft_budget,
                lane_budgets=engine._lane_budget_map(
                    soft_budget
                ),  # pylint: disable=protected-access
                lane_counts=defaultdict(int),
                lane_tokens=defaultdict(int),
                selected_count=0,
                consumed_tokens=2,
                sorted_candidates=[evidence_a],
                selected_ids=set(),
                apply_soft_limit=True,
            ),
            "soft_max_total_tokens",
        )
        prefix_budget = ContextBudget(
            max_total_tokens=10,
            max_prefix_tokens=2,
        )
        self.assertEqual(
            engine._selection_drop_detail(  # pylint: disable=protected-access
                candidate=evidence_a,
                budget=prefix_budget,
                lane_budgets=engine._lane_budget_map(
                    prefix_budget
                ),  # pylint: disable=protected-access
                lane_counts=defaultdict(int),
                lane_tokens=defaultdict(int),
                selected_count=0,
                consumed_tokens=2,
                sorted_candidates=[evidence_a],
                selected_ids=set(),
                apply_soft_limit=False,
            ),
            "max_prefix_tokens",
        )
        self.assertEqual(
            engine._reserved_tokens_remaining(  # pylint: disable=protected-access
                candidate_lane="operational_overlay",
                lane_budgets=engine._lane_budget_map(
                    total_budget
                ),  # pylint: disable=protected-access
                lane_tokens=defaultdict(int, {"recent_turn": 2}),
                sorted_candidates=[recent],
                selected_ids=set(),
            ),
            0,
        )
        self.assertEqual(
            engine._reserved_tokens_remaining(  # pylint: disable=protected-access
                candidate_lane="operational_overlay",
                lane_budgets=engine._lane_budget_map(
                    total_budget
                ),  # pylint: disable=protected-access
                lane_tokens=defaultdict(int),
                sorted_candidates=[recent],
                selected_ids={"recent-a"},
            ),
            0,
        )
        self.assertFalse(
            engine._lane_has_remaining_candidates(  # pylint: disable=protected-access
                lane="recent_turn",
                sorted_candidates=[recent],
                selected_ids={"recent-a"},
            )
        )

    async def test_prepare_and_commit_cover_replay_and_failure_paths(self) -> None:
        class _FailingCache(_Cache):
            async def put(self, *, namespace: str, key: str, value, ttl_seconds=None):
                _ = (namespace, key, value, ttl_seconds)
                raise RuntimeError("cache boom")

        logging_gateway = Mock()
        engine = DefaultContextEngine(
            config=SimpleNamespace(),
            logging_gateway=logging_gateway,
        )
        request = ContextTurnRequest(scope=_scope(), user_message="hello")

        registry = self._new_registry()
        registry.cache = _FailingCache()
        with patch(
            "mugen.core.service.context_engine._context_component_registry_provider",
            return_value=registry,
        ):
            prepared = await engine.prepare_turn(request)
            replay_result = ContextCommitResult(
                commit_token=prepared.commit_token,
                state_revision=99,
            )
            registry.commit_store.issued[prepared.commit_token][
                "state"
            ] = ContextCommitState.COMMITTED
            registry.commit_store.issued[prepared.commit_token][
                "result"
            ] = replay_result
            result = await engine.commit_turn(
                request=request,
                prepared=prepared,
                completion=CompletionResponse(content="assistant answer"),
                final_user_responses=[{"type": "text", "content": "assistant answer"}],
                outcome=TurnOutcome.COMPLETED,
            )

        self.assertIs(result, replay_result)
        self.assertEqual(registry.state_store.save_calls, [])
        logging_gateway.warning.assert_called()

        class _CommitFailingCache(_Cache):
            async def put(self, *, namespace: str, key: str, value, ttl_seconds=None):
                _ = (namespace, key, value, ttl_seconds)
                raise RuntimeError("commit cache boom")

        cache_registry = self._new_registry()
        logging_gateway.reset_mock()
        with patch(
            "mugen.core.service.context_engine._context_component_registry_provider",
            return_value=cache_registry,
        ):
            prepared = await engine.prepare_turn(request)
            cache_registry.cache = _CommitFailingCache()
            cache_result = await engine.commit_turn(
                request=request,
                prepared=prepared,
                completion=CompletionResponse(content="assistant answer"),
                final_user_responses=[{"type": "text", "content": "assistant answer"}],
                outcome=TurnOutcome.COMPLETED,
            )

        self.assertEqual(
            cache_result.warnings,
            ("cache_update_failed:RuntimeError",),
        )
        self.assertEqual(cache_result.cache_updates, {})
        logging_gateway.warning.assert_called()

        class _FailingStateStore(_StateStore):
            async def save(
                self,
                *,
                request,
                prepared,
                completion,
                final_user_responses,
                outcome,
            ) -> ContextState:
                _ = (
                    request,
                    prepared,
                    completion,
                    final_user_responses,
                    outcome,
                )
                raise RuntimeError("save boom")

        failing_registry = self._new_registry()
        failing_commit_store = _CommitStore()
        failing_commit_store.fail_commit = AsyncMock(  # type: ignore[method-assign]
            side_effect=failing_commit_store.fail_commit
        )
        failing_registry.commit_store = failing_commit_store
        failing_registry.state_store = _FailingStateStore(
            ContextState(current_objective="help", revision=1)
        )
        with patch(
            "mugen.core.service.context_engine._context_component_registry_provider",
            return_value=failing_registry,
        ):
            prepared = await engine.prepare_turn(request)
            with self.assertRaisesRegex(RuntimeError, "save boom"):
                await engine.commit_turn(
                    request=request,
                    prepared=prepared,
                    completion=CompletionResponse(content="assistant answer"),
                    final_user_responses=[
                        {"type": "text", "content": "assistant answer"}
                    ],
                    outcome=TurnOutcome.COMPLETED,
                )
        failing_commit_store.fail_commit.assert_awaited_once()

        class _FailingTraceSink(_TraceSink):
            async def record_commit(
                self,
                *,
                request,
                prepared,
                completion,
                final_user_responses,
                outcome,
                result,
            ) -> None:
                _ = (
                    request,
                    prepared,
                    completion,
                    final_user_responses,
                    outcome,
                    result,
                )
                raise RuntimeError("trace boom")

        trace_registry = self._new_registry()
        trace_registry.trace_sinks = (_FailingTraceSink(),)
        logging_gateway.reset_mock()
        with patch(
            "mugen.core.service.context_engine._context_component_registry_provider",
            return_value=trace_registry,
        ):
            prepared = await engine.prepare_turn(request)
            await engine.commit_turn(
                request=request,
                prepared=prepared,
                completion=CompletionResponse(content="assistant answer"),
                final_user_responses=[{"type": "text", "content": "assistant answer"}],
                outcome=TurnOutcome.COMPLETED,
            )
        logging_gateway.warning.assert_called()

    async def test_private_helpers_cover_renderer_source_and_guard_edges(self) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        request = ContextTurnRequest(
            scope=_scope(),
            user_message="hello",
            budget_hints={"max_total_tokens": 2, "max_prefix_tokens": 1},
        )

        class _MixedRenderer(IContextArtifactRenderer):
            render_class = "system_persona_policy_items"

            async def render(self, request, candidates, *, policy):
                _ = (request, candidates, policy)
                return [CompletionMessage(role="system", content={"ok": True}), "bad"]

        system_a = _candidate(
            artifact_id="persona-a",
            lane="system_persona_policy",
            content={"instruction": "one"},
        )
        system_b = _candidate(
            artifact_id="persona-b",
            lane="system_persona_policy",
            content={"instruction": "two"},
        )
        # pylint: disable=protected-access
        prepared_request = await engine._compile_completion_request(
            registry=SimpleNamespace(renderers=(_MixedRenderer(),)),
            request=request,
            policy=ContextPolicy(),
            selected_candidates=[system_a, system_b],
        )
        self.assertEqual(
            [message.role for message in prepared_request.messages], ["system", "user"]
        )

        with self.assertRaisesRegex(RuntimeError, "not registered"):
            await engine._compile_completion_request(
                registry=SimpleNamespace(renderers=()),
                request=request,
                policy=ContextPolicy(),
                selected_candidates=[
                    ContextCandidate(
                        artifact=ContextArtifact(
                            artifact_id="custom",
                            lane="system_persona_policy",
                            kind="custom",
                            render_class="missing_renderer",
                            content={"x": 1},
                            provenance=ContextProvenance(
                                contributor="test",
                                source_kind="unit",
                                tenant_id="tenant-1",
                            ),
                        ),
                        contributor="test",
                    )
                ],
            )

        with self.assertRaisesRegex(RuntimeError, "invalid renderer"):
            engine._renderer_map(
                SimpleNamespace(renderers=(object(),))
            )  # pylint: disable=protected-access

        class _BlankRenderer(IContextArtifactRenderer):
            render_class = ""

            async def render(self, request, candidates, *, policy):
                _ = (request, candidates, policy)
                return []

        with self.assertRaisesRegex(RuntimeError, "declare render_class"):
            engine._renderer_map(
                SimpleNamespace(renderers=(_BlankRenderer(),))
            )  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "missing render_class"):
            engine._render_class(  # pylint: disable=protected-access
                _candidate(
                    artifact_id="custom-lane",
                    lane="custom_lane",
                    content={"x": 1},
                )
            )

        no_source_candidate = ContextCandidate(
            artifact=ContextArtifact(
                artifact_id="no-source",
                lane="evidence",
                kind="evidence",
                content={"x": 1},
                provenance=ContextProvenance(
                    contributor="test",
                    source_kind="",
                    tenant_id="tenant-1",
                ),
            ),
            contributor="test",
        )
        self.assertIsNone(
            engine._candidate_source_ref(
                no_source_candidate
            )  # pylint: disable=protected-access
        )
        meta_source_candidate = ContextCandidate(
            artifact=ContextArtifact(
                artifact_id="meta-source",
                lane="evidence",
                kind="evidence",
                content={"x": 1},
                provenance=ContextProvenance(
                    contributor="test",
                    source_kind="knowledge",
                    source_id="fallback-id",
                    tenant_id="tenant-1",
                    metadata={"source_key": "meta-key"},
                ),
            ),
            contributor="test",
        )
        self.assertEqual(
            engine._candidate_source_ref(  # pylint: disable=protected-access
                meta_source_candidate
            ).source_key,
            "meta-key",
        )
        fallback_source_candidate = ContextCandidate(
            artifact=ContextArtifact(
                artifact_id="fallback-source",
                lane="evidence",
                kind="evidence",
                content={"x": 1},
                provenance=ContextProvenance(
                    contributor="test",
                    source_kind="knowledge",
                    source_id="fallback-id",
                    tenant_id="tenant-1",
                    metadata={"source_key": "   "},
                ),
            ),
            contributor="test",
        )
        self.assertEqual(
            engine._candidate_source_ref(  # pylint: disable=protected-access
                fallback_source_candidate
            ).source_key,
            "fallback-id",
        )

        self.assertEqual(
            len(
                engine._policy_source_rules(  # pylint: disable=protected-access
                    ContextPolicy(
                        source_allow=("knowledge",),
                        source_deny=("memory",),
                    )
                )
            ),
            2,
        )
        tightened = engine._effective_policy(  # pylint: disable=protected-access
            policy=ContextPolicy(),
            request=request,
        )
        self.assertEqual(tightened.budget.max_total_tokens, 2)
        self.assertEqual(tightened.budget.max_prefix_tokens, 1)
        same_policy = engine._effective_policy(  # pylint: disable=protected-access
            policy=ContextPolicy(),
            request=ContextTurnRequest(
                scope=_scope(),
                user_message="hello",
                budget_hints={"max_total_tokens": 9999},
            ),
        )
        self.assertEqual(
            same_policy.budget.max_total_tokens, ContextBudget().max_total_tokens
        )

        missing_source_kept, missing_source_dropped = (
            engine._apply_source_policy(  # pylint: disable=protected-access
                request=request,
                candidates=[
                    _candidate(
                        artifact_id="missing-ref",
                        lane="evidence",
                        content={"x": 1},
                        source_kind=" ",
                    )
                ],
                policy=ContextPolicy(
                    source_rules=(
                        ContextSourceRule(
                            effect=ContextSourcePolicyEffect.ALLOW,
                            source_key="required-key",
                        ),
                    )
                ),
            )
        )
        self.assertEqual(missing_source_kept, [])
        self.assertEqual(missing_source_dropped[0].reason_detail, "missing_source_ref")
        generic_source_kept, generic_source_dropped = (
            engine._apply_source_policy(  # pylint: disable=protected-access
                request=request,
                candidates=[
                    _candidate(
                        artifact_id="generic-ref",
                        lane="evidence",
                        content={"x": 1},
                        source_kind=" ",
                    )
                ],
                policy=ContextPolicy(
                    source_rules=(
                        ContextSourceRule(
                            effect=ContextSourcePolicyEffect.ALLOW,
                            kind="knowledge",
                            source_key="required-key",
                        ),
                    )
                ),
            )
        )
        self.assertEqual(generic_source_kept, [])
        self.assertEqual(generic_source_dropped[0].reason_detail, "source_allow")

        deny_only_kept, deny_only_dropped = (
            engine._apply_source_policy(  # pylint: disable=protected-access
                request=request,
                candidates=[
                    _candidate(
                        artifact_id="kept",
                        lane="evidence",
                        content={"x": 1},
                        source_kind="knowledge",
                    )
                ],
                policy=ContextPolicy(source_deny=("memory",)),
            )
        )
        self.assertEqual(
            [candidate.artifact.artifact_id for candidate in deny_only_kept], ["kept"]
        )
        self.assertEqual(deny_only_dropped, [])

        class _GuardResultGuard:
            name = "guard_result_guard"

            async def apply(self, request, candidates, *, policy, state):
                _ = (request, policy, state)
                return ContextGuardResult(
                    passed_candidates=(candidates[0],),
                    dropped_candidates=(
                        "bad-item",
                        ContextCandidate(
                            artifact=candidates[1].artifact,
                            contributor=candidates[1].contributor,
                            priority=candidates[1].priority,
                            score=candidates[1].score,
                            selected=False,
                            selection_reason=ContextSelectionReason.DROPPED_GUARD,
                            reason_detail="explicit_guard_result",
                        ),
                    ),
                )

        class _InvalidGuard:
            name = "invalid_guard"

            async def apply(self, request, candidates, *, policy, state):
                _ = (request, candidates, policy, state)
                return "bad"

        class _ExplicitDropGuard:
            name = "explicit_drop_guard"

            async def apply(self, request, candidates, *, policy, state):
                _ = (request, policy, state)
                return [
                    candidates[0],
                    ContextCandidate(
                        artifact=candidates[1].artifact,
                        contributor=candidates[1].contributor,
                        priority=candidates[1].priority,
                        score=candidates[1].score,
                        selected=False,
                        selection_reason=ContextSelectionReason.DROPPED_POLICY,
                        reason_detail="explicit_drop",
                    ),
                ]

        guard_candidates = [
            _candidate(artifact_id="keep", lane="evidence", content={"a": 1}),
            _candidate(artifact_id="drop", lane="evidence", content={"b": 1}),
        ]
        guarded, dropped = (
            await engine._apply_guards(  # pylint: disable=protected-access
                registry=SimpleNamespace(guards=(_GuardResultGuard(),)),
                request=request,
                candidates=guard_candidates,
                policy=ContextPolicy(),
                state=None,
            )
        )
        self.assertEqual(
            [candidate.artifact.artifact_id for candidate in guarded], ["keep"]
        )
        self.assertEqual(dropped[0].reason_detail, "explicit_guard_result")

        guarded, dropped = (
            await engine._apply_guards(  # pylint: disable=protected-access
                registry=SimpleNamespace(guards=(_InvalidGuard(),)),
                request=request,
                candidates=guard_candidates,
                policy=ContextPolicy(),
                state=None,
            )
        )
        self.assertEqual(guarded, [])
        self.assertEqual(dropped, [])

        guarded, dropped = (
            await engine._apply_guards(  # pylint: disable=protected-access
                registry=SimpleNamespace(guards=(_ExplicitDropGuard(),)),
                request=request,
                candidates=guard_candidates,
                policy=ContextPolicy(),
                state=None,
            )
        )
        self.assertEqual(
            [candidate.artifact.artifact_id for candidate in guarded], ["keep"]
        )
        self.assertEqual(dropped[0].reason_detail, "explicit_drop")

        sink = _TraceSink()
        await engine._record_prepare(  # pylint: disable=protected-access
            registry=SimpleNamespace(trace_sinks=(object(), sink)),
            request=request,
            prepared=PreparedContextTurn(
                completion_request=context_engine_module.CompletionRequest(messages=[]),
                bundle=ContextBundle(
                    policy=ContextPolicy(),
                    state=None,
                    selected_candidates=(),
                    dropped_candidates=(),
                    prefix_fingerprint="prefix",
                    cache_hints={},
                    trace={},
                ),
                state_handle="state",
                commit_token="commit",
                trace={},
            ),
        )
        self.assertEqual(len(sink.prepare_calls), 1)

    async def test_record_prepare_and_commit_cover_trace_sink_filtering(self) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        request = ContextTurnRequest(scope=_scope(), user_message="hello")
        sink = _TraceSink()
        result = ContextCommitResult(
            commit_token="commit",
            state_revision=1,
            memory_writes=(),
            cache_updates={},
        )
        prepared = PreparedContextTurn(
            completion_request=context_engine_module.CompletionRequest(messages=[]),
            bundle=ContextBundle(
                policy=ContextPolicy(),
                state=None,
                selected_candidates=(),
                dropped_candidates=(),
                prefix_fingerprint="prefix",
                cache_hints={},
                trace={},
            ),
            state_handle="state",
            commit_token="commit",
            trace={},
        )

        await engine._record_prepare(  # pylint: disable=protected-access
            registry=SimpleNamespace(trace_sinks=(sink,)),
            request=request,
            prepared=prepared,
        )
        await engine._record_prepare(  # pylint: disable=protected-access
            registry=SimpleNamespace(trace_sinks=(sink,)),
            request=request,
            prepared=PreparedContextTurn(
                completion_request=prepared.completion_request,
                bundle=ContextBundle(
                    policy=ContextPolicy(trace_enabled=False),
                    state=None,
                    selected_candidates=(),
                    dropped_candidates=(),
                    prefix_fingerprint="prefix",
                    cache_hints={},
                    trace={},
                ),
                state_handle="state",
                commit_token="commit",
                trace={},
            ),
        )
        await engine._record_commit(  # pylint: disable=protected-access
            registry=SimpleNamespace(trace_sinks=(object(), sink)),
            request=request,
            prepared=prepared,
            completion=None,
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETION_FAILED,
            result=result,
        )
        await engine._record_commit(  # pylint: disable=protected-access
            registry=SimpleNamespace(trace_sinks=(sink,)),
            request=request,
            prepared=PreparedContextTurn(
                completion_request=prepared.completion_request,
                bundle=ContextBundle(
                    policy=ContextPolicy(trace_enabled=False),
                    state=None,
                    selected_candidates=(),
                    dropped_candidates=(),
                    prefix_fingerprint="prefix",
                    cache_hints={},
                    trace={},
                ),
                state_handle="state",
                commit_token="commit",
                trace={},
            ),
            completion=None,
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETION_FAILED,
            result=result,
        )

        self.assertEqual(len(sink.prepare_calls), 1)
        self.assertEqual(len(sink.commit_calls), 1)
