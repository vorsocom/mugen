"""Unit tests for mugen.core.service.context_engine.DefaultContextEngine."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import mugen.core.service.context_engine as context_engine_module
from mugen.core.contract.context import (
    ContextArtifact,
    ContextBundle,
    ContextBudget,
    ContextCandidate,
    ContextCommitResult,
    ContextPolicy,
    ContextProvenance,
    ContextRetentionPolicy,
    ContextScope,
    ContextSelectionReason,
    ContextState,
    ContextTurnRequest,
    IContextTraceSink,
    MemoryWrite,
    MemoryWriteType,
    PreparedContextTurn,
)
from mugen.core.contract.context.result import TurnOutcome
from mugen.core.contract.gateway.completion import CompletionResponse
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
                max_total_tokens=4,
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
            contributors=(
                _Contributor(
                    "lane_source",
                    [persona, overlay, recent_turn, evidence, overflow, cross_tenant],
                ),
                _Contributor("dedupe_source", [duplicate]),
            ),
            guards=(_Guard(dropped_artifact_ids={"audit-1"}),),
            rankers=(_Ranker(),),
            memory_writer=_MemoryWriter(),
            cache=_Cache(),
            trace_sinks=(_TraceSink(),),
        )
        return registry

    async def test_prepare_turn_compiles_messages_and_tracks_dropped_candidates(self) -> None:
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
            ["system", "system", "system", "system", "assistant", "user"],
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
            prepared.completion_request.messages[3].content["context_lane"],
            "evidence",
        )
        self.assertEqual(prepared.completion_request.messages[-1].content, "hello")

        self.assertEqual(
            [candidate.artifact.artifact_id for candidate in prepared.bundle.selected_candidates],
            ["persona-1", "overlay-1", "turn-1", "kb-1"],
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
        self.assertEqual(result.cache_updates["working_set"], working_set_cache_key(_scope()))
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
                    final_user_responses=[{"type": "text", "content": "assistant answer"}],
                    outcome=TurnOutcome.COMPLETED,
                )

        self.assertEqual(registry.state_store.save_calls, [])

    def test_context_component_registry_provider_uses_di_container(self) -> None:
        registry = object()
        container = SimpleNamespace(get_required_ext_service=Mock(return_value=registry))

        with patch.object(context_engine_module.di, "container", container):
            self.assertIs(
                context_engine_module._context_component_registry_provider(),
                registry,
            )

        container.get_required_ext_service.assert_called_once_with(
            context_engine_module.di.EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY
        )

    async def test_prepare_and_commit_skip_optional_cache_memory_and_trace_when_disabled(
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
        policy = ContextPolicy(contributor_allow=("kept",), contributor_deny=("denied",))
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

        collected, dropped = await engine._collect_candidates(  # pylint: disable=protected-access
            registry=registry,
            request=ContextTurnRequest(scope=_scope(), user_message="hello"),
            policy=policy,
            state=None,
        )

        self.assertEqual([item.artifact.artifact_id for item in collected], ["kept"])
        self.assertEqual(dropped, [])
        logging_gateway.warning.assert_called_once()

        denied_only, _ = await engine._collect_candidates(  # pylint: disable=protected-access
            registry=SimpleNamespace(contributors=(_Contributor("denied", [candidate]),)),
            request=ContextTurnRequest(scope=_scope(), user_message="hello"),
            policy=ContextPolicy(contributor_deny=("denied",)),
            state=None,
        )
        self.assertEqual(denied_only, [])

    async def test_apply_guards_filters_invalid_items_and_records_drop_reason(self) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        candidate = _candidate(
            artifact_id="guarded",
            lane="evidence",
            content={"snippet": "ok"},
        )

        guarded, dropped = await engine._apply_guards(  # pylint: disable=protected-access
            registry=SimpleNamespace(guards=(_PassthroughGuard(),)),
            request=ContextTurnRequest(scope=_scope(), user_message="hello"),
            candidates=[candidate],
            policy=ContextPolicy(),
            state=None,
        )

        self.assertEqual(guarded, [candidate])
        self.assertEqual(dropped, [])

    def test_private_helper_methods_cover_payload_sort_and_validation_paths(self) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
        recent_messages = engine._recent_turn_messages(  # pylint: disable=protected-access
            [
                _candidate(
                    artifact_id="skip-content",
                    lane="recent_turn",
                    content="bad",
                ),
                _candidate(
                    artifact_id="skip-role",
                    lane="recent_turn",
                    content={"role": 1, "content": "bad"},
                ),
                _candidate(
                    artifact_id="keep",
                    lane="recent_turn",
                    content={"role": "assistant", "content": "ok"},
                ),
            ]
        )
        wrapped_user_payload = engine._user_message_payload(  # pylint: disable=protected-access
            ContextTurnRequest(
                scope=_scope(),
                user_message="hello",
                message_context=[{"type": "seed", "content": "ctx"}],
            )
        )
        bare_user_payload = engine._user_message_payload(  # pylint: disable=protected-access
            ContextTurnRequest(scope=_scope(), user_message="hello")
        )
        prepared = engine._compile_completion_request(  # pylint: disable=protected-access
            request=ContextTurnRequest(scope=_scope(), user_message="hello"),
            policy=ContextPolicy(metadata={"policy": "strict"}),
            state=None,
            selected_candidates=[],
        )
        prepared_turn = context_engine_module.PreparedContextTurn(
            completion_request=prepared,
            bundle=ContextBundle(
                policy=ContextPolicy(),
                state=None,
                selected_candidates=(),
                dropped_candidates=(),
                prefix_fingerprint=None,
                cache_hints={},
                trace={},
            ),
            state_handle="state",
            commit_token=engine._commit_token(  # pylint: disable=protected-access
                ContextTurnRequest(scope=_scope(), user_message="hello"),
                engine._prefix_fingerprint(prepared),  # pylint: disable=protected-access
            ),
            trace={},
        )

        self.assertIsNone(engine._state_payload(None))  # pylint: disable=protected-access
        self.assertIsNone(
            engine._lane_payload([], lane="evidence")  # pylint: disable=protected-access
        )
        self.assertEqual([message.content for message in recent_messages], ["ok"])
        self.assertEqual(bare_user_payload, "hello")
        self.assertEqual(wrapped_user_payload["message"], "hello")
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
        engine._validate_commit_token(  # pylint: disable=protected-access
            request=ContextTurnRequest(scope=_scope(), user_message="hello"),
            prepared=prepared_turn,
        )
        self.assertEqual(
            engine._get_optional_cache(SimpleNamespace()),  # pylint: disable=protected-access
            None,
        )

        with self.assertRaisesRegex(RuntimeError, "missing policy_resolver"):
            engine._get_policy_resolver(SimpleNamespace())  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "missing state_store"):
            engine._get_state_store(SimpleNamespace())  # pylint: disable=protected-access

        self.assertEqual(
            prepared.vendor_params["context_policy"],
            {"policy": "strict"},
        )

    def test_selection_and_dedup_cover_budget_edges(self) -> None:
        engine = DefaultContextEngine(config=SimpleNamespace(), logging_gateway=Mock())
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
        selected, dropped = engine._select_candidates(  # pylint: disable=protected-access
            candidates=[evidence_a, evidence_b],
            policy=ContextPolicy(
                budget=ContextBudget(
                    max_total_tokens=4,
                    max_selected_artifacts=8,
                    max_evidence_items=1,
                )
            ),
        )
        self.assertEqual([item.artifact.artifact_id for item in selected], ["evidence-a"])
        self.assertEqual(dropped[0].reason_detail, "max_evidence_items")

        selected, dropped = engine._select_candidates(  # pylint: disable=protected-access
            candidates=[evidence_a, overlay],
            policy=ContextPolicy(
                budget=ContextBudget(
                    max_total_tokens=10,
                    max_selected_artifacts=1,
                    max_evidence_items=8,
                )
            ),
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(dropped[0].reason_detail, "max_selected_artifacts")

        selected, dropped = engine._select_candidates(  # pylint: disable=protected-access
            candidates=[overlay],
            policy=ContextPolicy(
                budget=ContextBudget(
                    max_total_tokens=1,
                    max_selected_artifacts=8,
                    max_evidence_items=8,
                )
            ),
        )
        self.assertEqual(selected, [])
        self.assertEqual(dropped[0].reason_detail, "max_total_tokens")

        deduped, dedup_dropped = engine._deduplicate_candidates(  # pylint: disable=protected-access
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
        self.assertEqual(deduped[0].artifact.content, {"new": True})
        self.assertEqual(dedup_dropped[0].reason_detail, "replaced_by_higher_score")

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
            trace_enabled=True,
        )
        await engine._record_prepare(  # pylint: disable=protected-access
            registry=SimpleNamespace(trace_sinks=(sink,)),
            request=request,
            prepared=prepared,
            trace_enabled=False,
        )
        await engine._record_commit(  # pylint: disable=protected-access
            registry=SimpleNamespace(trace_sinks=(object(), sink)),
            request=request,
            prepared=prepared,
            completion=None,
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETION_FAILED,
            result=result,
            trace_enabled=True,
        )
        await engine._record_commit(  # pylint: disable=protected-access
            registry=SimpleNamespace(trace_sinks=(sink,)),
            request=request,
            prepared=prepared,
            completion=None,
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETION_FAILED,
            result=result,
            trace_enabled=False,
        )

        self.assertEqual(len(sink.prepare_calls), 1)
        self.assertEqual(len(sink.commit_calls), 1)
