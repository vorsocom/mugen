"""Coverage-focused tests for context_engine plugin runtime services."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import (
    ContextArtifact,
    ContextBundle,
    ContextBudget,
    ContextCandidate,
    ContextCommitResult,
    ContextPolicy,
    ContextProvenance,
    ContextRedactionPolicy,
    ContextRetentionPolicy,
    ContextScope,
    ContextSelectionReason,
    ContextState,
    ContextTurnRequest,
    MemoryWrite,
    MemoryWriteType,
    PreparedContextTurn,
)
from mugen.core.contract.context.result import TurnOutcome
from mugen.core.contract.gateway.completion import (
    CompletionMessage,
    CompletionRequest,
    CompletionResponse,
)
import mugen.core.plugin.context_engine.service.contributor as contributor_module
from mugen.core.plugin.context_engine.model import (
    ContextCacheRecord,
    ContextContributorBinding,
    ContextEventLog,
    ContextMemoryRecord,
    ContextPolicy as ContextPolicyModel,
    ContextProfile,
    ContextSourceBinding,
    ContextStateSnapshot,
    ContextTrace,
    ContextTracePolicy,
)
from mugen.core.plugin.context_engine.service.contributor import (
    AuditContributor,
    ChannelOrchestrationContributor,
    KnowledgePackContributor,
    MemoryContributor,
    OpsCaseContributor,
    PersonaPolicyContributor,
    RecentTurnContributor,
    StateContributor,
)
import mugen.core.plugin.context_engine.service.runtime as runtime_module
from mugen.core.plugin.context_engine.service.registry import ContextComponentRegistry
from mugen.core.plugin.context_engine.service.runtime import (
    DefaultContextGuard,
    DefaultContextPolicyResolver,
    DefaultContextRanker,
    DefaultMemoryWriter,
    RelationalContextCache,
    RelationalContextStateStore,
    RelationalContextTraceSink,
)


def _tenant_uuid() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


def _scope(
    *,
    tenant_id: str | None = None,
    sender_id: str | None = "user-1",
    conversation_id: str | None = "room-1",
    case_id: str | None = None,
) -> ContextScope:
    return ContextScope(
        tenant_id=tenant_id or str(_tenant_uuid()),
        platform="matrix",
        channel_id="matrix",
        room_id="room-1",
        sender_id=sender_id,
        conversation_id=conversation_id,
        case_id=case_id,
        workflow_id="wf-1",
    )


def _request(
    *,
    scope: ContextScope | None = None,
    user_message="hello",
    trace_id: str | None = "trace-1",
    ingress_metadata: dict | None = None,
) -> ContextTurnRequest:
    return ContextTurnRequest(
        scope=scope or _scope(),
        user_message=user_message,
        message_id="msg-1",
        trace_id=trace_id,
        ingress_metadata=ingress_metadata or {},
    )


def _policy(
    *,
    trace_enabled: bool = True,
    cache_enabled: bool = True,
    allow_long_term_memory: bool = True,
    blocked_sensitivity_labels: tuple[str, ...] = (),
    persona: str | None = None,
) -> ContextPolicy:
    metadata = {"policy": "test"}
    if persona is not None:
        metadata["persona"] = persona
    return ContextPolicy(
        budget=ContextBudget(
            max_total_tokens=128,
            max_selected_artifacts=8,
            max_recent_turns=4,
            max_recent_messages=4,
            max_evidence_items=4,
            max_prefix_tokens=64,
        ),
        redaction=ContextRedactionPolicy(
            redact_sensitive=True,
            blocked_sensitivity_labels=blocked_sensitivity_labels,
        ),
        retention=ContextRetentionPolicy(
            allow_long_term_memory=allow_long_term_memory,
            require_partition_for_global_memory=True,
            cache_ttl_seconds=30,
            trace_ttl_seconds=60,
            memory_ttl_seconds=15,
        ),
        trace_enabled=trace_enabled,
        cache_enabled=cache_enabled,
        metadata=metadata,
    )


def _state() -> ContextState:
    return ContextState(
        current_objective="Solve the issue",
        entities={"order_id": "123"},
        constraints=["be concise"],
        unresolved_slots=["email"],
        commitments=["follow up"],
        safety_flags=["audit"],
        routing={"queue": "ops"},
        summary="summary",
        revision=2,
        metadata={"k": "v"},
    )


def _candidate(
    *,
    artifact_id: str,
    lane: str,
    kind: str = "artifact",
    content=None,
    tenant_id: str | None = None,
    sensitivity: tuple[str, ...] = (),
    score: float = 0.0,
    priority: int = 10,
) -> ContextCandidate:
    return ContextCandidate(
        artifact=ContextArtifact(
            artifact_id=artifact_id,
            lane=lane,
            kind=kind,
            content={} if content is None else content,
            provenance=ContextProvenance(
                contributor="test",
                source_kind="unit",
                tenant_id=tenant_id or str(_tenant_uuid()),
            ),
            sensitivity=sensitivity,
            estimated_token_cost=8,
            trust=0.9,
            freshness=0.8,
        ),
        contributor="test",
        priority=priority,
        score=score,
    )


def _prepared(*, trace_enabled: bool = True, selected_candidates=()) -> PreparedContextTurn:
    bundle = ContextBundle(
        policy=_policy(trace_enabled=trace_enabled),
        state=_state(),
        selected_candidates=tuple(selected_candidates),
        dropped_candidates=(),
        prefix_fingerprint="prefix-1",
        cache_hints={"prefix_fingerprint": "prefix-1"},
        trace={"selected": [{"artifact_id": "a1"}], "dropped": []},
    )
    return PreparedContextTurn(
        completion_request=CompletionRequest(
            messages=[CompletionMessage(role="user", content="hello")]
        ),
        bundle=bundle,
        state_handle="state-1",
        commit_token="commit-1",
        trace={"selected": [{"artifact_id": "a1"}], "dropped": []},
    )


class TestMugenContextEnginePluginRuntime(unittest.IsolatedAsyncioTestCase):
    """Exercises plugin runtime services without DI/bootstrap."""

    async def test_models_use_core_runtime_schema(self) -> None:
        tables = (
            ContextProfile.__table__,
            ContextPolicyModel.__table__,
            ContextContributorBinding.__table__,
            ContextSourceBinding.__table__,
            ContextTracePolicy.__table__,
            ContextStateSnapshot.__table__,
            ContextEventLog.__table__,
            ContextMemoryRecord.__table__,
            ContextCacheRecord.__table__,
            ContextTrace.__table__,
        )

        self.assertTrue(all(table.schema == "mugen" for table in tables))
        self.assertIn("client_profile_key", ContextProfile.__table__.c)
        self.assertIn("persona", ContextProfile.__table__.c)

    async def test_policy_resolver_covers_default_and_configured_policy_paths(self) -> None:
        profile_service = SimpleNamespace(
            list=AsyncMock(
                side_effect=[
                    [
                        SimpleNamespace(
                            id=uuid.uuid4(),
                            tenant_id=_tenant_uuid(),
                            name="matrix-default",
                            platform="matrix",
                            channel_key=None,
                            client_profile_key=None,
                            persona="Default persona.",
                            is_default=True,
                            is_active=True,
                            policy_id=None,
                        )
                    ],
                    [
                        SimpleNamespace(
                            id=uuid.uuid4(),
                            tenant_id=_tenant_uuid(),
                            name="matrix-fallback",
                            platform="matrix",
                            channel_key="matrix",
                            client_profile_key=None,
                            persona="Fallback persona.",
                            is_default=True,
                            is_active=True,
                            policy_id=None,
                        ),
                        SimpleNamespace(
                            id=uuid.uuid4(),
                            tenant_id=_tenant_uuid(),
                            name="matrix-policy",
                            platform="matrix",
                            channel_key="matrix",
                            client_profile_key="matrix-primary",
                            persona="Escalation persona.",
                            is_default=False,
                            is_active=True,
                            policy_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                        )
                    ],
                ]
            )
        )
        policy_service = SimpleNamespace(
            list=AsyncMock(
                side_effect=[
                    [],
                    [
                        SimpleNamespace(
                            id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                            tenant_id=_tenant_uuid(),
                            policy_key="strict",
                            is_default=False,
                            budget_json={
                                "max_total_tokens": 42,
                                "max_selected_artifacts": 3,
                                "max_recent_turns": 2,
                                "max_recent_messages": 2,
                                "max_evidence_items": 1,
                                "max_prefix_tokens": 21,
                            },
                            redaction_json={
                                "redact_sensitive": False,
                                "blocked_sensitivity_labels": ["secret"],
                                "allowed_sensitivity_labels": ["audit"],
                            },
                            retention_json={
                                "allow_long_term_memory": False,
                                "require_partition_for_global_memory": False,
                                "memory_ttl_seconds": 9,
                                "trace_ttl_seconds": 8,
                                "cache_ttl_seconds": 7,
                            },
                            contributor_allow=["knowledge_pack"],
                            contributor_deny=["audit"],
                            source_allow=["knowledge"],
                            source_deny=["memory"],
                            trace_enabled=False,
                            cache_enabled=False,
                        )
                    ],
                ]
            )
        )
        contributor_binding_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        contributor_key="persona_policy",
                        platform="matrix",
                        channel_key=None,
                        is_enabled=True,
                    ),
                    SimpleNamespace(
                        contributor_key="ignored",
                        platform="telegram",
                        channel_key=None,
                        is_enabled=True,
                    ),
                ]
            )
        )
        source_binding_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        source_key="source-a",
                        source_kind="knowledge",
                        platform="matrix",
                        channel_key="matrix",
                        is_enabled=True,
                    ),
                    SimpleNamespace(
                        source_key="source-b",
                        source_kind="audit",
                        platform="line",
                        channel_key=None,
                        is_enabled=True,
                    ),
                ]
            )
        )
        trace_policy_service = SimpleNamespace(
            list=AsyncMock(
                side_effect=[
                    [
                        SimpleNamespace(
                            name="trace-default",
                            capture_prepare=True,
                            capture_commit=False,
                            capture_selected_items=True,
                            capture_dropped_items=False,
                        )
                    ],
                    [
                        SimpleNamespace(
                            name="trace-strict",
                            capture_prepare=False,
                            capture_commit=True,
                            capture_selected_items=False,
                            capture_dropped_items=True,
                        )
                    ],
                ]
            )
        )

        resolver = DefaultContextPolicyResolver(
            profile_service=profile_service,
            policy_service=policy_service,
            contributor_binding_service=contributor_binding_service,
            source_binding_service=source_binding_service,
            trace_policy_service=trace_policy_service,
        )

        default_policy = await resolver.resolve_policy(_request())
        self.assertEqual(default_policy.policy_key, "default")
        self.assertEqual(default_policy.profile_key, "matrix-default")
        self.assertEqual(default_policy.contributor_allow, ("persona_policy",))
        self.assertEqual(default_policy.source_allow, ("knowledge",))
        self.assertTrue(default_policy.trace_enabled)
        self.assertEqual(default_policy.metadata["persona"], "Default persona.")
        self.assertEqual(default_policy.metadata["trace_policy_name"], "trace-default")

        configured_policy = await resolver.resolve_policy(
            _request(
                ingress_metadata={
                    "ingress_route": {
                        "client_profile_key": "matrix-primary",
                    }
                }
            )
        )
        self.assertEqual(configured_policy.policy_key, "strict")
        self.assertEqual(configured_policy.profile_key, "matrix-policy")
        self.assertEqual(configured_policy.budget.max_total_tokens, 42)
        self.assertEqual(configured_policy.budget.max_evidence_items, 1)
        self.assertFalse(configured_policy.redaction.redact_sensitive)
        self.assertEqual(
            configured_policy.redaction.blocked_sensitivity_labels,
            ("secret",),
        )
        self.assertFalse(configured_policy.retention.allow_long_term_memory)
        self.assertEqual(configured_policy.retention.cache_ttl_seconds, 7)
        self.assertEqual(configured_policy.contributor_allow, ("knowledge_pack",))
        self.assertEqual(configured_policy.contributor_deny, ("audit",))
        self.assertEqual(configured_policy.source_allow, ("knowledge",))
        self.assertEqual(configured_policy.source_deny, ("memory",))
        self.assertFalse(configured_policy.trace_enabled)
        self.assertFalse(configured_policy.cache_enabled)
        self.assertEqual(configured_policy.metadata["persona"], "Escalation persona.")
        self.assertEqual(configured_policy.metadata["trace_policy_name"], "trace-strict")
        self.assertFalse(configured_policy.metadata["trace_capture_selected"])
        self.assertTrue(configured_policy.metadata["trace_capture_dropped"])
        self.assertEqual(configured_policy.metadata["source_bindings"], ["source-a", "source-b"])

    async def test_runtime_and_contributor_helpers_cover_remaining_edge_paths(self) -> None:
        circular: list[object] = []
        circular.append(circular)

        self.assertEqual(contributor_module._estimate_token_cost(None), 0)  # pylint: disable=protected-access
        self.assertEqual(contributor_module._estimate_token_cost(circular), 32)  # pylint: disable=protected-access
        self.assertTrue(
            contributor_module._memory_partition_matches(None, _scope())  # pylint: disable=protected-access
        )
        self.assertEqual(
            contributor_module._excerpt_text("  short  "),  # pylint: disable=protected-access
            "short",
        )
        self.assertEqual(
            runtime_module._assistant_text(  # pylint: disable=protected-access
                completion=CompletionResponse(content="fallback"),
                final_user_responses=[
                    {"type": "image", "content": "skip"},
                    {"type": "text", "content": "   "},
                    {"type": "text", "content": "preferred"},
                ],
            ),
            "preferred",
        )
        self.assertIsNone(
            runtime_module._assistant_text(  # pylint: disable=protected-access
                completion=CompletionResponse(content="   "),
                final_user_responses=[],
            )
        )

        global_default = DefaultContextPolicyResolver._default_policy(  # pylint: disable=protected-access
            _scope(tenant_id=str(GLOBAL_TENANT_ID))
        )
        self.assertTrue(global_default.retention.require_partition_for_global_memory)
        self.assertEqual(
            runtime_module._request_client_profile_key(  # pylint: disable=protected-access
                _request(
                    ingress_metadata={
                        "ingress_route": {"client_profile_key": " matrix-route "},
                        "client_profile_key": "matrix-top-level",
                    }
                )
            ),
            "matrix-route",
        )
        self.assertEqual(
            runtime_module._request_client_profile_key(  # pylint: disable=protected-access
                _request(ingress_metadata={"client_profile_key": " matrix-top-level "})
            ),
            "matrix-top-level",
        )
        self.assertIsNone(
            DefaultContextPolicyResolver._select_profile(  # pylint: disable=protected-access
                _scope(),
                None,
                [],
            )
        )
        wildcard_profile = SimpleNamespace(
            name="wildcard",
            platform="matrix",
            channel_key="matrix",
            client_profile_key=None,
            is_default=True,
        )
        exact_profile = SimpleNamespace(
            name="exact",
            platform="matrix",
            channel_key="matrix",
            client_profile_key="matrix-primary",
            is_default=False,
        )
        self.assertIs(
            DefaultContextPolicyResolver._select_profile(  # pylint: disable=protected-access
                _scope(),
                "matrix-primary",
                [wildcard_profile, exact_profile],
            ),
            exact_profile,
        )
        self.assertIs(
            DefaultContextPolicyResolver._select_profile(  # pylint: disable=protected-access
                _scope(),
                None,
                [wildcard_profile, exact_profile],
            ),
            wildcard_profile,
        )
        profile = SimpleNamespace(policy_id=uuid.uuid4())
        self.assertIsNone(
            DefaultContextPolicyResolver._select_policy(profile, [])  # pylint: disable=protected-access
        )
        fallback_policy = SimpleNamespace(id=uuid.uuid4(), is_default=False)
        self.assertIs(
            DefaultContextPolicyResolver._select_policy(profile, [fallback_policy]),  # pylint: disable=protected-access
            fallback_policy,
        )
        default_policy = SimpleNamespace(is_default=True)
        self.assertIs(
            DefaultContextPolicyResolver._select_policy(None, [default_policy]),  # pylint: disable=protected-access
            default_policy,
        )

    async def test_state_store_load_save_and_clear_cover_snapshot_and_event_paths(self) -> None:
        existing_row = SimpleNamespace(
            id=uuid.uuid4(),
            revision=2,
            current_objective="Existing objective",
            entities={"ticket": "A-1"},
            constraints=["constraint"],
            unresolved_slots=["email"],
            commitments=["reply"],
            safety_flags=["audit"],
            routing={"queue": "ops"},
            summary="summary",
            attributes={"k": "v"},
        )
        snapshot_service = SimpleNamespace(
            get=AsyncMock(side_effect=[None, existing_row, None, existing_row]),
            create=AsyncMock(),
            update=AsyncMock(),
            delete=AsyncMock(),
        )
        event_log_rsg = SimpleNamespace(delete_many=AsyncMock())
        event_log_service = SimpleNamespace(
            _rsg=event_log_rsg,
            table="context_event_log",
            count=AsyncMock(return_value=3),
            create=AsyncMock(),
        )
        store = RelationalContextStateStore(
            snapshot_service=snapshot_service,
            event_log_service=event_log_service,
        )

        self.assertIsNone(await store.load(_request()))

        loaded = await store.load(_request())
        self.assertEqual(loaded.current_objective, "Existing objective")
        self.assertEqual(loaded.metadata, {"k": "v"})

        created_state = await store.save(
            request=_request(trace_id="trace-create"),
            prepared=_prepared(),
            completion=None,
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETION_FAILED,
        )
        self.assertEqual(created_state.summary, None)
        snapshot_service.create.assert_awaited_once()
        self.assertEqual(event_log_service.create.await_count, 1)

        updated_state = await store.save(
            request=_request(trace_id="trace-update", user_message={"prompt": "hi"}),
            prepared=_prepared(),
            completion=CompletionResponse(content="assistant answer"),
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETED,
        )
        self.assertEqual(updated_state.summary, "assistant answer")
        self.assertEqual(updated_state.routing["tenant_resolution"], None)
        snapshot_service.update.assert_awaited_once()
        self.assertEqual(event_log_service.create.await_count, 3)

        await store.clear(_request())
        snapshot_service.delete.assert_awaited()
        event_log_rsg.delete_many.assert_awaited()
        self.assertEqual(
            store._objective_from_request(_request(user_message={"nested": True})),  # pylint: disable=protected-access
            "{'nested': True}",
        )

    async def test_relational_cache_covers_parse_get_put_and_invalidate(self) -> None:
        tenant_id = _tenant_uuid()
        cache_service = SimpleNamespace(
            get=AsyncMock(
                side_effect=[
                    None,
                    SimpleNamespace(
                        id=uuid.uuid4(),
                        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                        hit_count=0,
                        payload={"expired": True},
                    ),
                    SimpleNamespace(
                        id=uuid.uuid4(),
                        expires_at=None,
                        hit_count=1,
                        payload={"value": 1},
                    ),
                    None,
                    SimpleNamespace(id=uuid.uuid4()),
                ]
            ),
            create=AsyncMock(),
            update=AsyncMock(),
            delete=AsyncMock(),
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(id=uuid.uuid4(), cache_key="other:keep"),
                    SimpleNamespace(id=uuid.uuid4(), cache_key="prefix:drop"),
                    SimpleNamespace(id=uuid.uuid4(), cache_key=None),
                ]
            ),
        )
        cache = RelationalContextCache(cache_service=cache_service)
        key = f"tenant:{tenant_id}:prefix:drop"

        with self.assertRaisesRegex(RuntimeError, "tenant:<uuid> prefix"):
            cache._parse_key("bad-key")  # pylint: disable=protected-access

        self.assertIsNone(await cache.get(namespace="working_set", key=key))
        self.assertIsNone(await cache.get(namespace="working_set", key=key))
        self.assertEqual(await cache.get(namespace="working_set", key=key), {"value": 1})
        cache_service.update.assert_awaited()

        await cache.put(namespace="working_set", key=key, value={"a": 1}, ttl_seconds=10)
        await cache.put(namespace="working_set", key=key, value={"b": 2}, ttl_seconds=None)
        cache_service.create.assert_awaited_once()
        cache_service.update.assert_awaited()

        deleted = await cache.invalidate(namespace="working_set", key_prefix=f"tenant:{tenant_id}:prefix:")
        self.assertEqual(deleted, 1)

    async def test_trace_sink_memory_writer_guard_and_ranker_cover_edge_paths(self) -> None:
        trace_service = SimpleNamespace(create=AsyncMock())
        audit_service = SimpleNamespace(create=AsyncMock())
        sink = RelationalContextTraceSink(
            trace_service=trace_service,
            audit_trace_service=audit_service,
        )
        selected = (
            _candidate(artifact_id="selected-1", lane="evidence"),
        )
        prepared = _prepared(trace_enabled=True, selected_candidates=selected)
        request = _request(user_message="I prefer tea and my name is Alex")
        result = ContextCommitResult(
            commit_token="commit-1",
            state_revision=3,
            memory_writes=(
                MemoryWrite(
                    write_type=MemoryWriteType.SUMMARY,
                    content={"summary": "done"},
                    provenance=ContextProvenance(
                        contributor="test",
                        source_kind="unit",
                        tenant_id=request.scope.tenant_id,
                    ),
                ),
            ),
            cache_updates={"working_set": "tenant:key"},
        )
        await sink.record_prepare(request=request, prepared=prepared)
        await sink.record_commit(
            request=request,
            prepared=prepared,
            completion=CompletionResponse(content="done", model="gpt-test"),
            final_user_responses=[{"type": "text", "content": "done"}],
            outcome=TurnOutcome.COMPLETED,
            result=result,
        )
        self.assertEqual(trace_service.create.await_count, 2)
        audit_service.create.assert_awaited()

        trace_service.create.reset_mock()
        no_trace_prepared = _prepared(trace_enabled=False)
        await sink.record_prepare(request=request, prepared=no_trace_prepared)
        await sink.record_commit(
            request=request,
            prepared=no_trace_prepared,
            completion=CompletionResponse(content="done"),
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETED,
            result=result,
        )
        self.assertEqual(trace_service.create.await_count, 0)

        sink_without_audit = RelationalContextTraceSink(
            trace_service=trace_service,
            audit_trace_service=None,
        )
        await sink_without_audit.record_prepare(request=request, prepared=prepared)
        self.assertEqual(trace_service.create.await_count, 1)

        memory_service = SimpleNamespace(create=AsyncMock())
        writer = DefaultMemoryWriter(memory_service=memory_service)
        self.assertEqual(
            await writer.persist(
                request=_request(scope=_scope(tenant_id=str(GLOBAL_TENANT_ID), sender_id=None, conversation_id=None)),
                prepared=_prepared(),
                completion=CompletionResponse(content="done"),
                final_user_responses=[],
                outcome=TurnOutcome.COMPLETED,
            ),
            [],
        )
        writes = await writer.persist(
            request=request,
            prepared=prepared,
            completion=CompletionResponse(content="done"),
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETED,
        )
        self.assertEqual([write.write_type for write in writes], [MemoryWriteType.EPISODE, MemoryWriteType.PREFERENCE, MemoryWriteType.FACT])
        self.assertEqual(memory_service.create.await_count, 3)
        self.assertIsNone(writer._expires_at(None))  # pylint: disable=protected-access
        self.assertIsNotNone(writer._expires_at(1))  # pylint: disable=protected-access

        fallback_writes = writer._derive_writes(  # pylint: disable=protected-access
            request=_request(),
            prepared=_prepared(selected_candidates=()),
            assistant_response="done",
        )
        self.assertEqual(fallback_writes[0].provenance.contributor, "context_engine")
        self.assertEqual(
            len(
                writer._derive_writes(  # pylint: disable=protected-access
                    request=_request(user_message="hello"),
                    prepared=prepared,
                    assistant_response=None,
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                writer._derive_writes(  # pylint: disable=protected-access
                    request=_request(user_message={"hello": "world"}),
                    prepared=prepared,
                    assistant_response=None,
                )
            ),
            1,
        )
        writer._derive_writes = Mock(return_value=[])  # type: ignore[method-assign]  # pylint: disable=protected-access
        self.assertEqual(
            await writer.persist(
                request=request,
                prepared=prepared,
                completion=CompletionResponse(content="done"),
                final_user_responses=[],
                outcome=TurnOutcome.COMPLETED,
            ),
            [],
        )
        self.assertEqual(
            await writer.persist(
                request=request,
                prepared=prepared,
                completion=None,
                final_user_responses=[],
                outcome=TurnOutcome.NO_RESPONSE,
            ),
            [],
        )

        guard = DefaultContextGuard()
        guarded = await guard.apply(
            _request(scope=_scope(tenant_id=str(GLOBAL_TENANT_ID), sender_id=None, conversation_id=None)),
            [
                _candidate(artifact_id="tenant-mismatch", lane="evidence", tenant_id="other-tenant"),
                _candidate(
                    artifact_id="blocked",
                    lane="evidence",
                    tenant_id=str(GLOBAL_TENANT_ID),
                    sensitivity=("secret",),
                ),
                _candidate(artifact_id="global-memory", lane="evidence", kind="memory", tenant_id=str(GLOBAL_TENANT_ID)),
                _candidate(
                    artifact_id="kept",
                    lane="recent_turn",
                    tenant_id=str(GLOBAL_TENANT_ID),
                ),
            ],
            policy=_policy(blocked_sensitivity_labels=("secret",)),
            state=None,
        )
        reasons = {
            candidate.artifact.artifact_id: candidate.selection_reason
            for candidate in guarded
        }
        self.assertEqual(reasons["tenant-mismatch"], ContextSelectionReason.DROPPED_TENANT_MISMATCH)
        self.assertEqual(reasons["blocked"], ContextSelectionReason.DROPPED_GUARD)
        self.assertEqual(reasons["global-memory"], ContextSelectionReason.DROPPED_POLICY)
        self.assertIsNone(reasons["kept"])

        ranked = await DefaultContextRanker().rank(
            _request(),
            [
                _candidate(artifact_id="recent", lane="recent_turn", score=0.0),
                _candidate(artifact_id="system", lane="system_persona_policy", score=0.0),
            ],
            policy=_policy(),
            state=None,
        )
        self.assertGreater(ranked[1].score, ranked[0].score)

    async def test_registry_and_contributors_cover_runtime_paths(self) -> None:
        registry = ContextComponentRegistry()
        registry.register_contributor("contributor")
        registry.register_guard("guard")
        registry.register_ranker("ranker")
        registry.register_trace_sink("trace")
        registry.set_policy_resolver("resolver")
        registry.set_state_store("store")
        registry.set_memory_writer("writer")
        registry.set_cache("cache")
        self.assertEqual(registry.contributors, ["contributor"])
        self.assertEqual(registry.guards, ["guard"])
        self.assertEqual(registry.rankers, ["ranker"])
        self.assertEqual(registry.trace_sinks, ["trace"])
        self.assertEqual(registry.policy_resolver, "resolver")
        self.assertEqual(registry.state_store, "store")
        self.assertEqual(registry.memory_writer, "writer")
        self.assertEqual(registry.cache, "cache")

        policy = _policy()
        request = _request(
            ingress_metadata={"tenant_resolution": {"mode": "resolved", "source": "test"}}
        )

        persona_candidates = await PersonaPolicyContributor().collect(
            request,
            policy=_policy(persona="Be concise."),
            state=None,
        )
        self.assertEqual(persona_candidates[0].artifact.content["persona"], "Be concise.")

        self.assertEqual(await StateContributor().collect(request, policy=policy, state=None), [])
        state_candidates = await StateContributor().collect(request, policy=policy, state=_state())
        self.assertEqual(state_candidates[0].artifact.lane, "bounded_control_state")

        event_log_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(id=1, role="assistant", content="second", trace_id="trace-2"),
                    SimpleNamespace(id=2, role="user", content="first", trace_id="trace-1"),
                ]
            )
        )
        recent_candidates = await RecentTurnContributor(
            event_log_service=event_log_service
        ).collect(request, policy=policy, state=None)
        self.assertEqual([c.artifact.content["content"] for c in recent_candidates], ["first", "second"])

        knowledge_scope_service = SimpleNamespace(
            list_published_revisions=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        id=uuid.uuid4(),
                        revision_number=1,
                        body="x" * 1200,
                        body_json=None,
                        channel="matrix",
                        locale="en-US",
                        category="faq",
                        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    ),
                    SimpleNamespace(
                        id=uuid.uuid4(),
                        revision_number=2,
                        body=None,
                        body_json={"answer": "json"},
                        channel="matrix",
                        locale=None,
                        category=None,
                        published_at=None,
                    ),
                    SimpleNamespace(
                        id=uuid.uuid4(),
                        revision_number=3,
                        body=None,
                        body_json=None,
                        channel="matrix",
                        locale=None,
                        category=None,
                        published_at=None,
                    ),
                ]
            )
        )
        knowledge_candidates = await KnowledgePackContributor(
            knowledge_scope_service=knowledge_scope_service
        ).collect(
            _request(ingress_metadata={"locale": "en-US", "category": "faq"}),
            policy=policy,
            state=None,
        )
        self.assertEqual(len(knowledge_candidates), 2)
        self.assertTrue(knowledge_candidates[0].artifact.content["excerpt"].endswith("..."))

        conversation_state_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        status="open",
                        route_key="route-1",
                        assigned_queue_name="support",
                        assigned_service_key="svc",
                        fallback_mode="bot",
                        fallback_target="queue",
                        fallback_reason="busy",
                        is_fallback_active=True,
                        is_throttled=False,
                    )
                ]
            )
        )
        work_item_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        trace_id="trace-1",
                        linked_case_id=uuid.uuid4(),
                        linked_workflow_instance_id=uuid.uuid4(),
                    )
                ]
            )
        )
        channel_candidates = await ChannelOrchestrationContributor(
            conversation_state_service=conversation_state_service,
            work_item_service=work_item_service,
        ).collect(request, policy=policy, state=None)
        self.assertEqual(channel_candidates[0].artifact.lane, "operational_overlay")
        self.assertEqual(
            await ChannelOrchestrationContributor(
                conversation_state_service=SimpleNamespace(list=AsyncMock(return_value=[])),
                work_item_service=SimpleNamespace(list=AsyncMock(return_value=[])),
            ).collect(
                _request(
                    scope=ContextScope(
                        tenant_id=str(_tenant_uuid()),
                        platform="matrix",
                        channel_id="matrix",
                        room_id=None,
                        sender_id=None,
                        conversation_id=None,
                    )
                ),
                policy=policy,
                state=None,
            ),
            [],
        )
        no_trace_channel = await ChannelOrchestrationContributor(
            conversation_state_service=conversation_state_service,
            work_item_service=SimpleNamespace(list=AsyncMock(return_value=[])),
        ).collect(_request(trace_id=None), policy=policy, state=None)
        self.assertEqual(no_trace_channel[0].artifact.content["work_item"], None)
        self.assertEqual(
            await ChannelOrchestrationContributor(
                conversation_state_service=SimpleNamespace(list=AsyncMock(return_value=[])),
                work_item_service=SimpleNamespace(list=AsyncMock(return_value=[])),
            ).collect(_request(trace_id=None), policy=policy, state=None),
            [],
        )

        case_id = str(uuid.uuid4())
        case_service = SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid.UUID(case_id),
                    case_number="CASE-1",
                    title="Network issue",
                    status="open",
                    priority="high",
                    severity="sev2",
                    queue_name="ops",
                    owner_user_id=uuid.uuid4(),
                    resolution_summary="Investigating",
                )
            )
        )
        case_event_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        event_type="status_change",
                        status_from="new",
                        status_to="open",
                        note="triaged",
                    )
                ]
            )
        )
        ops_case = OpsCaseContributor(
            case_service=case_service,
            case_event_service=case_event_service,
        )
        self.assertEqual(await ops_case.collect(_request(), policy=policy, state=None), [])
        case_candidates = await ops_case.collect(
            _request(scope=_scope(case_id=case_id)),
            policy=policy,
            state=None,
        )
        self.assertEqual(case_candidates[0].artifact.content["case_number"], "CASE-1")
        self.assertEqual(
            await OpsCaseContributor(
                case_service=SimpleNamespace(get=AsyncMock(return_value=None)),
                case_event_service=case_event_service,
            ).collect(_request(scope=_scope(case_id=case_id)), policy=policy, state=None),
            [],
        )

        audit_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        stage="start",
                        source_plugin="ops_connector",
                        action_name="invoke",
                        details_json={"status": "ok"},
                    )
                ]
            )
        )
        audit_candidates = await AuditContributor(audit_trace_service=audit_service).collect(
            request,
            policy=policy,
            state=None,
        )
        self.assertEqual(audit_candidates[0].artifact.kind, "audit_trace")
        self.assertEqual(
            await AuditContributor(audit_trace_service=audit_service).collect(
                _request(trace_id=None),
                policy=policy,
                state=None,
            ),
            [],
        )
        self.assertEqual(
            await AuditContributor(
                audit_trace_service=SimpleNamespace(list=AsyncMock(return_value=[]))
            ).collect(
                request,
                policy=policy,
                state=None,
            ),
            [],
        )

        memory_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        id=uuid.uuid4(),
                        memory_type="fact",
                        content={"statement": "prefers tea"},
                        subject="user-1",
                        provenance={"source": "unit"},
                        confidence=0.7,
                        scope_partition={"sender_id": "user-1"},
                        updated_at=datetime.now(timezone.utc),
                        is_deleted=False,
                    ),
                    SimpleNamespace(
                        id=uuid.uuid4(),
                        memory_type="fact",
                        content={"statement": "wrong user"},
                        subject="user-2",
                        provenance={},
                        confidence=0.7,
                        scope_partition={"sender_id": "user-2"},
                        updated_at=datetime.now(timezone.utc),
                        is_deleted=False,
                    ),
                    SimpleNamespace(
                        id=uuid.uuid4(),
                        memory_type="fact",
                        content={"statement": "global unpartitioned"},
                        subject=None,
                        provenance={},
                        confidence=0.7,
                        scope_partition=None,
                        updated_at=datetime.now(timezone.utc),
                        is_deleted=False,
                    ),
                ]
            )
        )
        memory_contributor = MemoryContributor(memory_service=memory_service)
        self.assertEqual(
            await memory_contributor.collect(request, policy=_policy(allow_long_term_memory=False), state=None),
            [],
        )
        kept_memory = await memory_contributor.collect(request, policy=policy, state=None)
        self.assertEqual(len(kept_memory), 2)
        global_request = _request(
            scope=_scope(tenant_id=str(GLOBAL_TENANT_ID), sender_id="user-1", conversation_id="room-1")
        )
        global_kept = await memory_contributor.collect(global_request, policy=policy, state=None)
        self.assertEqual(len(global_kept), 1)
        self.assertEqual(
            await MemoryContributor(
                memory_service=SimpleNamespace(
                    list=AsyncMock(
                        return_value=[
                            SimpleNamespace(
                                id=uuid.uuid4(),
                                memory_type="fact",
                                content={"statement": "global unpartitioned"},
                                subject=None,
                                provenance={},
                                confidence=0.7,
                                scope_partition=None,
                                updated_at=datetime.now(timezone.utc),
                                is_deleted=False,
                            )
                        ]
                    )
                )
            ).collect(
                _request(
                    scope=_scope(
                        tenant_id=str(GLOBAL_TENANT_ID),
                        sender_id="user-1",
                        conversation_id="room-1",
                    )
                ),
                policy=policy,
                state=None,
            ),
            [],
        )
