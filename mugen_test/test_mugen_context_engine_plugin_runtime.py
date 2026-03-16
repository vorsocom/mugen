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
    ContextCommitState,
    ContextPolicy,
    ContextProvenance,
    ContextRedactionPolicy,
    ContextRetentionPolicy,
    ContextScope,
    ContextSelectionReason,
    ContextState,
    ContextSourcePolicyEffect,
    ContextSourceRef,
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
    ContextCommitLedger,
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
    RecentTurnMessageRenderer,
    RelationalContextCache,
    RelationalContextCommitStore,
    RelationalContextStateStore,
    RelationalContextTraceSink,
    StructuredLaneRenderer,
)
from mugen.core.utility.rdbms_schema import CONTEXT_ENGINE_SCHEMA_TOKEN


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


def _prepared(
    *, trace_enabled: bool = True, selected_candidates=()
) -> PreparedContextTurn:
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

    async def test_models_use_plugin_runtime_schema_token(self) -> None:
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
            ContextCommitLedger.__table__,
            ContextTrace.__table__,
        )

        self.assertTrue(
            all(table.schema == CONTEXT_ENGINE_SCHEMA_TOKEN for table in tables)
        )
        self.assertIn("service_route_key", ContextProfile.__table__.c)
        self.assertIn("client_profile_key", ContextProfile.__table__.c)
        self.assertIn("service_route_key", ContextContributorBinding.__table__.c)
        self.assertIn("service_route_key", ContextSourceBinding.__table__.c)
        self.assertIn("persona", ContextProfile.__table__.c)

    async def test_policy_resolver_covers_default_and_configured_policy_paths(
        self,
    ) -> None:
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
                            service_route_key=None,
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
                            service_route_key=None,
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
                            service_route_key="customer_inbox",
                            client_profile_key="matrix-primary",
                            persona="Escalation persona.",
                            is_default=False,
                            is_active=True,
                            policy_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                        ),
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
                        service_route_key=None,
                        is_enabled=True,
                    ),
                    SimpleNamespace(
                        contributor_key="ignored",
                        platform="telegram",
                        channel_key=None,
                        service_route_key=None,
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
                        service_route_key="customer_inbox",
                        is_enabled=True,
                    ),
                    SimpleNamespace(
                        source_key="source-b",
                        source_kind="audit",
                        platform="line",
                        channel_key=None,
                        service_route_key=None,
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
        self.assertEqual(default_policy.source_allow, ())
        self.assertEqual(default_policy.source_rules, ())
        self.assertTrue(default_policy.trace_enabled)
        self.assertEqual(default_policy.metadata["persona"], "Default persona.")
        self.assertIsNone(default_policy.metadata["service_route_key"])
        self.assertEqual(default_policy.metadata["trace_policy_name"], "trace-default")

        configured_policy = await resolver.resolve_policy(
            _request(
                ingress_metadata={
                    "ingress_route": {
                        "service_route_key": "customer_inbox",
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
        self.assertEqual(configured_policy.source_rules[0].source_key, "source-a")
        self.assertEqual(
            configured_policy.source_rules[-1].effect,
            ContextSourcePolicyEffect.DENY,
        )
        self.assertFalse(configured_policy.trace_enabled)
        self.assertFalse(configured_policy.cache_enabled)
        self.assertEqual(configured_policy.metadata["persona"], "Escalation persona.")
        self.assertEqual(
            configured_policy.metadata["service_route_key"],
            "customer_inbox",
        )
        self.assertEqual(
            configured_policy.metadata["trace_policy_name"], "trace-strict"
        )
        self.assertFalse(configured_policy.metadata["trace_capture_selected"])
        self.assertTrue(configured_policy.metadata["trace_capture_dropped"])
        self.assertEqual(
            configured_policy.metadata["source_bindings"], ["source-a", "source-b"]
        )

    async def test_runtime_and_contributor_helpers_cover_remaining_edge_paths(
        self,
    ) -> None:
        circular: list[object] = []
        circular.append(circular)

        self.assertEqual(
            contributor_module._estimate_token_cost(None), 0
        )  # pylint: disable=protected-access
        self.assertEqual(
            contributor_module._estimate_token_cost(circular), 32
        )  # pylint: disable=protected-access
        self.assertTrue(
            contributor_module._memory_partition_matches(
                None, _scope()
            )  # pylint: disable=protected-access
        )
        self.assertEqual(
            contributor_module._excerpt_text(
                "  short  "
            ),  # pylint: disable=protected-access
            "short",
        )
        self.assertEqual(
            contributor_module._memory_source_key(
                SimpleNamespace(memory_key=" mem-1 ", id=uuid.uuid4())
            ),
            "mem-1",
        )
        self.assertIsNone(
            contributor_module._memory_source_key(
                SimpleNamespace(memory_key=" ", id=None)
            )
        )
        self.assertEqual(
            contributor_module._normalize_revision_source_key(
                SimpleNamespace(source_key=" rev-source ")
            ),
            "rev-source",
        )
        self.assertIsNone(
            contributor_module._normalize_revision_source_key(SimpleNamespace())
        )
        # pylint: disable=protected-access
        self.assertEqual(
            DefaultContextPolicyResolver._dedupe_texts(
                (" allow ", None, "allow", " deny ")
            ),
            ("allow", "deny"),
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

        # pylint: disable=protected-access
        global_default = DefaultContextPolicyResolver._default_policy(
            _scope(tenant_id=str(GLOBAL_TENANT_ID))
        )
        self.assertTrue(global_default.retention.require_partition_for_global_memory)
        request_client_profile_key = runtime_module._request_client_profile_key
        request_service_route_key = runtime_module._request_service_route_key
        select_profile = DefaultContextPolicyResolver._select_profile
        binding_matches_scope = DefaultContextPolicyResolver._binding_matches_scope
        source_binding_matches_scope = (
            DefaultContextPolicyResolver._source_binding_matches_scope
        )
        self.assertEqual(
            request_client_profile_key(  # pylint: disable=protected-access
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
            request_client_profile_key(  # pylint: disable=protected-access
                _request(ingress_metadata={"client_profile_key": " matrix-top-level "})
            ),
            "matrix-top-level",
        )
        self.assertEqual(
            request_service_route_key(  # pylint: disable=protected-access
                _request(
                    ingress_metadata={
                        "ingress_route": {
                            "service_route_key": " customer.inbox ",
                        },
                        "service_route_key": "top-level",
                    }
                )
            ),
            "customer.inbox",
        )
        self.assertEqual(
            request_service_route_key(  # pylint: disable=protected-access
                _request(ingress_metadata={"service_route_key": " top-level "})
            ),
            "top-level",
        )
        self.assertIsNone(
            select_profile(  # pylint: disable=protected-access
                _scope(),
                None,
                None,
                [],
            )
        )
        wildcard_profile = SimpleNamespace(
            name="wildcard",
            platform="matrix",
            channel_key="matrix",
            service_route_key=None,
            client_profile_key=None,
            is_default=True,
        )
        exact_service_route_profile = SimpleNamespace(
            name="service-route",
            platform="matrix",
            channel_key="matrix",
            service_route_key="customer.inbox",
            client_profile_key=None,
            is_default=False,
        )
        exact_client_profile = SimpleNamespace(
            name="client-profile",
            platform="matrix",
            channel_key="matrix",
            service_route_key=None,
            client_profile_key="matrix-primary",
            is_default=False,
        )
        self.assertIs(
            select_profile(  # pylint: disable=protected-access
                _scope(),
                "customer.inbox",
                "matrix-primary",
                [
                    wildcard_profile,
                    exact_client_profile,
                    exact_service_route_profile,
                ],
            ),
            exact_service_route_profile,
        )
        self.assertIs(
            select_profile(  # pylint: disable=protected-access
                _scope(),
                None,
                None,
                [wildcard_profile, exact_client_profile],
            ),
            wildcard_profile,
        )
        self.assertTrue(
            binding_matches_scope(  # pylint: disable=protected-access
                SimpleNamespace(
                    platform="matrix",
                    channel_key="matrix",
                    service_route_key="customer.inbox",
                ),
                _scope(),
                "customer.inbox",
            )
        )
        self.assertFalse(
            binding_matches_scope(  # pylint: disable=protected-access
                SimpleNamespace(
                    platform="matrix",
                    channel_key="matrix",
                    service_route_key="valet.core",
                ),
                _scope(),
                "customer.inbox",
            )
        )
        self.assertTrue(
            source_binding_matches_scope(  # pylint: disable=protected-access
                SimpleNamespace(
                    platform="matrix",
                    channel_key="matrix",
                    service_route_key=None,
                ),
                _scope(),
                "customer.inbox",
            )
        )
        self.assertFalse(
            source_binding_matches_scope(  # pylint: disable=protected-access
                SimpleNamespace(
                    platform="matrix",
                    channel_key="matrix",
                    service_route_key="valet.core",
                ),
                _scope(),
                "customer.inbox",
            )
        )
        profile = SimpleNamespace(policy_id=uuid.uuid4())
        self.assertIsNone(
            DefaultContextPolicyResolver._select_policy(
                profile, []
            )  # pylint: disable=protected-access
        )
        fallback_policy = SimpleNamespace(id=uuid.uuid4(), is_default=False)
        self.assertIs(
            DefaultContextPolicyResolver._select_policy(
                profile, [fallback_policy]
            ),  # pylint: disable=protected-access
            fallback_policy,
        )
        default_policy = SimpleNamespace(is_default=True)
        self.assertIs(
            DefaultContextPolicyResolver._select_policy(
                None, [default_policy]
            ),  # pylint: disable=protected-access
            default_policy,
        )

    async def test_state_store_load_save_and_clear_cover_snapshot_and_event_paths(
        self,
    ) -> None:
        existing_row = SimpleNamespace(
            id=uuid.uuid4(),
            scope_key=runtime_module.scope_key(_scope()),
            revision=2,
            row_version=3,
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
            create=AsyncMock(),
            delete=AsyncMock(),
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
            request=_request(
                trace_id="trace-create",
                ingress_metadata={"service_route_key": "top-level-route"},
            ),
            prepared=_prepared(),
            completion=None,
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETION_FAILED,
        )
        self.assertEqual(created_state.summary, None)
        self.assertEqual(created_state.routing["service_route_key"], "top-level-route")
        snapshot_service.create.assert_awaited_once()
        self.assertEqual(event_log_service.create.await_count, 1)
        self.assertEqual(
            event_log_service.create.await_args_list[0].args[0]["sequence_no"],
            1,
        )

        updated_state = await store.save(
            request=_request(
                trace_id="trace-update",
                user_message={"prompt": "hi"},
                ingress_metadata={
                    "ingress_route": {
                        "service_route_key": "route-envelope",
                    }
                },
            ),
            prepared=_prepared(),
            completion=CompletionResponse(content="assistant answer"),
            final_user_responses=[],
            outcome=TurnOutcome.COMPLETED,
        )
        self.assertEqual(updated_state.summary, "summary")
        self.assertEqual(updated_state.routing["service_route_key"], "route-envelope")
        self.assertEqual(updated_state.routing["tenant_resolution"], None)
        snapshot_service.update.assert_awaited_once()
        self.assertEqual(event_log_service.create.await_count, 3)
        self.assertEqual(
            event_log_service.create.await_args_list[1].args[0]["sequence_no"],
            5,
        )
        self.assertEqual(
            event_log_service.create.await_args_list[2].args[0]["sequence_no"],
            6,
        )

        await store.clear(_request())
        snapshot_service.delete.assert_awaited()
        event_log_rsg.delete_many.assert_awaited()
        self.assertEqual(
            store._objective_from_request(
                _request(user_message={"nested": True})
            ),  # pylint: disable=protected-access
            "{'nested': True}",
        )

    async def test_state_store_retries_snapshot_conflicts_and_rolls_back_failed_events(
        self,
    ) -> None:
        scope_key_value = runtime_module.scope_key(_scope())
        first_row = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=_tenant_uuid(),
            scope_key=scope_key_value,
            platform="matrix",
            channel_id="matrix",
            room_id="room-1",
            sender_id="user-1",
            conversation_id="room-1",
            case_id=None,
            workflow_id="wf-1",
            current_objective="before",
            entities={"ticket": "A-1"},
            constraints=["constraint"],
            unresolved_slots=["email"],
            commitments=["reply"],
            safety_flags=["audit"],
            routing={"service_route_key": "route.before"},
            summary="summary",
            revision=2,
            last_message_id="msg-before",
            last_trace_id="trace-before",
            attributes={"outcome": "completed"},
            row_version=4,
        )
        replacement_row = SimpleNamespace(
            **{
                **first_row.__dict__,
                "id": uuid.uuid4(),
                "revision": 3,
                "row_version": 7,
            }
        )

        class _SnapshotService:
            def __init__(self) -> None:
                self.get_calls = 0
                self.deleted: list[dict] = []
                self.rows = {
                    ("tenant_scope", 0): None,
                    ("tenant_scope", 1): replacement_row,
                }
                self.current = replacement_row

            async def get(self, where):
                _ = where
                self.get_calls += 1
                if self.get_calls <= 2:
                    return self.rows[("tenant_scope", self.get_calls - 1)]
                return self.current

            async def create(self, payload):
                raise RuntimeError("duplicate snapshot row")

            async def update_with_row_version(
                self,
                where,
                *,
                expected_row_version,
                changes,
            ):
                _ = where
                if self.current.row_version != expected_row_version:
                    return None
                for key, value in changes.items():
                    setattr(self.current, key, value)
                self.current.row_version += 1
                return self.current

            async def delete_with_row_version(self, where, *, expected_row_version):
                _ = where
                if self.current.row_version != expected_row_version:
                    return None
                self.deleted.append(where)
                self.current = None
                return None

            async def delete(self, where):
                self.deleted.append(where)
                self.current = None
                return None

        snapshot_service = _SnapshotService()
        event_log_service = SimpleNamespace(
            create=AsyncMock(
                side_effect=[None, RuntimeError("assistant event failed")]
            ),
            delete=AsyncMock(),
            _rsg=SimpleNamespace(delete_many=AsyncMock()),
            table="context_event_log",
        )
        store = RelationalContextStateStore(
            snapshot_service=snapshot_service,
            event_log_service=event_log_service,
        )

        with self.assertRaisesRegex(RuntimeError, "assistant event failed"):
            await store.save(
                request=_request(trace_id="trace-rollback"),
                prepared=_prepared(),
                completion=CompletionResponse(content="assistant answer"),
                final_user_responses=[],
                outcome=TurnOutcome.COMPLETED,
            )

        self.assertEqual(snapshot_service.current.revision, 3)
        self.assertEqual(snapshot_service.current.current_objective, "before")
        self.assertEqual(event_log_service.delete.await_count, 2)
        self.assertEqual(
            event_log_service.delete.await_args_list[0].args[0]["sequence_no"],
            8,
        )
        self.assertEqual(
            event_log_service.delete.await_args_list[1].args[0]["sequence_no"],
            7,
        )

        stale_row = SimpleNamespace(**{**first_row.__dict__, "row_version": 10})

        class _ConflictSnapshotService:
            async def get(self, where):
                _ = where
                return stale_row

            async def update_with_row_version(
                self,
                where,
                *,
                expected_row_version,
                changes,
            ):
                _ = (where, expected_row_version, changes)
                return None

        conflict_store = RelationalContextStateStore(
            snapshot_service=_ConflictSnapshotService(),
            event_log_service=SimpleNamespace(
                create=AsyncMock(),
                delete=AsyncMock(),
                _rsg=SimpleNamespace(delete_many=AsyncMock()),
                table="context_event_log",
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "snapshot update conflict"):
            await conflict_store.save(
                request=_request(trace_id="trace-conflict"),
                prepared=_prepared(),
                completion=None,
                final_user_responses=[],
                outcome=TurnOutcome.COMPLETION_FAILED,
            )

    async def test_state_store_save_adds_notes_when_snapshot_rollback_conflicts(
        self,
    ) -> None:
        current_row = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=_tenant_uuid(),
            scope_key=runtime_module.scope_key(_scope()),
            platform="matrix",
            channel_id="matrix",
            room_id="room-1",
            sender_id="user-1",
            conversation_id="room-1",
            case_id=None,
            workflow_id="wf-1",
            current_objective="before",
            entities={"ticket": "A-1"},
            constraints=["constraint"],
            unresolved_slots=["email"],
            commitments=["reply"],
            safety_flags=["audit"],
            routing={"service_route_key": "route.before"},
            summary="summary",
            revision=2,
            last_message_id="msg-before",
            last_trace_id="trace-before",
            attributes={"outcome": "completed"},
            row_version=4,
        )

        class _RollbackConflictSnapshotService:
            def __init__(self, row) -> None:
                self.row = row
                self.update_calls = 0

            async def get(self, where):
                _ = where
                return self.row

            async def update_with_row_version(
                self,
                where,
                *,
                expected_row_version,
                changes,
            ):
                _ = where
                self.update_calls += 1
                if self.update_calls == 2:
                    return None
                if self.row.row_version != expected_row_version:
                    return None
                for key, value in changes.items():
                    setattr(self.row, key, value)
                self.row.row_version += 1
                return self.row

        snapshot_service = _RollbackConflictSnapshotService(current_row)
        event_log_service = SimpleNamespace(
            create=AsyncMock(
                side_effect=[None, RuntimeError("assistant event failed")]
            ),
            delete=AsyncMock(),
            _rsg=SimpleNamespace(delete_many=AsyncMock()),
            table="context_event_log",
        )
        store = RelationalContextStateStore(
            snapshot_service=snapshot_service,
            event_log_service=event_log_service,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "assistant event failed",
        ) as error_ctx:
            await store.save(
                request=_request(trace_id="trace-note"),
                prepared=_prepared(),
                completion=CompletionResponse(content="assistant answer"),
                final_user_responses=[],
                outcome=TurnOutcome.COMPLETED,
            )

        self.assertIn(
            "Context state rollback failed",
            "\n".join(getattr(error_ctx.exception, "__notes__", [])),
        )

    async def test_state_store_snapshot_helpers_cover_create_and_rollback_edges(
        self,
    ) -> None:
        payload = {"tenant_id": _tenant_uuid(), "scope_key": "scope"}
        request = _request(trace_id="trace-edge")
        tenant_id = _tenant_uuid()
        scope_key_value = runtime_module.scope_key(request.scope)

        create_failure_store = RelationalContextStateStore(
            snapshot_service=SimpleNamespace(
                create=AsyncMock(side_effect=RuntimeError("create failed")),
                get=AsyncMock(return_value=None),
            ),
            event_log_service=SimpleNamespace(),
        )
        with self.assertRaisesRegex(RuntimeError, "create failed"):
            await create_failure_store._persist_snapshot(
                tenant_id=tenant_id,
                scope_key_value=scope_key_value,
                existing=None,
                payload=payload,
            )

        revision_mismatch_row = SimpleNamespace(
            id=uuid.uuid4(),
            revision=9,
            last_message_id=request.message_id,
            last_trace_id=request.trace_id,
            row_version=1,
        )
        message_mismatch_row = SimpleNamespace(
            id=uuid.uuid4(),
            revision=3,
            last_message_id="other-message",
            last_trace_id=request.trace_id,
            row_version=1,
        )
        trace_mismatch_row = SimpleNamespace(
            id=uuid.uuid4(),
            revision=3,
            last_message_id=request.message_id,
            last_trace_id="other-trace",
            row_version=1,
        )
        guard_service = SimpleNamespace(
            get=AsyncMock(
                side_effect=[
                    None,
                    revision_mismatch_row,
                    message_mismatch_row,
                    trace_mismatch_row,
                ]
            ),
            delete=AsyncMock(),
            update=AsyncMock(),
        )
        guard_store = RelationalContextStateStore(
            snapshot_service=guard_service,
            event_log_service=SimpleNamespace(),
        )
        for _ in range(4):
            await guard_store._rollback_snapshot(
                tenant_id=tenant_id,
                scope_key_value=scope_key_value,
                request=request,
                previous_payload={"revision": 2},
                failed_revision=3,
            )
        guard_service.delete.assert_not_awaited()
        guard_service.update.assert_not_awaited()

        delete_with_version_service = SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid.uuid4(),
                    revision=3,
                    last_message_id=request.message_id,
                    last_trace_id=request.trace_id,
                    row_version=5,
                )
            ),
            delete_with_row_version=AsyncMock(return_value=None),
            delete=AsyncMock(),
        )
        delete_with_version_store = RelationalContextStateStore(
            snapshot_service=delete_with_version_service,
            event_log_service=SimpleNamespace(),
        )
        await delete_with_version_store._rollback_snapshot(
            tenant_id=tenant_id,
            scope_key_value=scope_key_value,
            request=request,
            previous_payload=None,
            failed_revision=3,
        )
        delete_with_version_service.delete_with_row_version.assert_awaited_once()
        delete_with_version_service.delete.assert_not_awaited()

        fallback_delete_service = SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=uuid.uuid4(),
                    revision=3,
                    last_message_id=request.message_id,
                    last_trace_id=request.trace_id,
                    row_version="stale",
                )
            ),
            delete=AsyncMock(),
        )
        fallback_delete_store = RelationalContextStateStore(
            snapshot_service=fallback_delete_service,
            event_log_service=SimpleNamespace(),
        )
        await fallback_delete_store._rollback_snapshot(
            tenant_id=tenant_id,
            scope_key_value=scope_key_value,
            request=request,
            previous_payload=None,
            failed_revision=3,
        )
        fallback_delete_service.delete.assert_awaited_once()

    async def test_state_store_event_rollback_edges_cover_missing_delete_and_user_only(
        self,
    ) -> None:
        request = _request(trace_id="trace-events")
        tenant_id = _tenant_uuid()
        scope_key_value = runtime_module.scope_key(request.scope)

        no_delete_store = RelationalContextStateStore(
            snapshot_service=SimpleNamespace(),
            event_log_service=SimpleNamespace(),
        )
        await no_delete_store._rollback_turn_events(
            tenant_id=tenant_id,
            scope_key_value=scope_key_value,
            assistant_response=None,
            revision=3,
        )

        delete_service = SimpleNamespace(delete=AsyncMock())
        delete_store = RelationalContextStateStore(
            snapshot_service=SimpleNamespace(),
            event_log_service=delete_service,
        )
        await delete_store._rollback_turn_events(
            tenant_id=tenant_id,
            scope_key_value=scope_key_value,
            assistant_response=None,
            revision=3,
        )
        self.assertEqual(delete_service.delete.await_count, 1)
        self.assertEqual(
            delete_service.delete.await_args_list[0].args[0]["sequence_no"],
            5,
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
        self.assertEqual(
            await cache.get(namespace="working_set", key=key), {"value": 1}
        )
        cache_service.update.assert_awaited()

        await cache.put(
            namespace="working_set", key=key, value={"a": 1}, ttl_seconds=10
        )
        await cache.put(
            namespace="working_set", key=key, value={"b": 2}, ttl_seconds=None
        )
        cache_service.create.assert_awaited_once()
        cache_service.update.assert_awaited()

        deleted = await cache.invalidate(
            namespace="working_set", key_prefix=f"tenant:{tenant_id}:prefix:"
        )
        self.assertEqual(deleted, 1)

    async def test_trace_sink_memory_writer_guard_and_ranker_cover_edge_paths(
        self,
    ) -> None:
        trace_service = SimpleNamespace(create=AsyncMock())
        audit_service = SimpleNamespace(create=AsyncMock())
        sink = RelationalContextTraceSink(
            trace_service=trace_service,
            audit_trace_service=audit_service,
        )
        selected = (_candidate(artifact_id="selected-1", lane="evidence"),)
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
                request=_request(
                    scope=_scope(
                        tenant_id=str(GLOBAL_TENANT_ID),
                        sender_id=None,
                        conversation_id=None,
                    )
                ),
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
        self.assertEqual(
            [write.write_type for write in writes],
            [MemoryWriteType.EPISODE, MemoryWriteType.PREFERENCE, MemoryWriteType.FACT],
        )
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
        writer._derive_writes = Mock(  # type: ignore[method-assign]
            return_value=[]
        )  # pylint: disable=protected-access
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
            _request(
                scope=_scope(
                    tenant_id=str(GLOBAL_TENANT_ID),
                    sender_id=None,
                    conversation_id=None,
                )
            ),
            [
                _candidate(
                    artifact_id="tenant-mismatch",
                    lane="evidence",
                    tenant_id="other-tenant",
                ),
                _candidate(
                    artifact_id="blocked",
                    lane="evidence",
                    tenant_id=str(GLOBAL_TENANT_ID),
                    sensitivity=("secret",),
                ),
                _candidate(
                    artifact_id="global-memory",
                    lane="evidence",
                    kind="memory",
                    tenant_id=str(GLOBAL_TENANT_ID),
                ),
                _candidate(
                    artifact_id="kept",
                    lane="recent_turn",
                    tenant_id=str(GLOBAL_TENANT_ID),
                ),
            ],
            policy=_policy(blocked_sensitivity_labels=("secret",)),
            state=None,
        )
        self.assertEqual(
            [candidate.artifact.artifact_id for candidate in guarded.passed_candidates],
            ["kept"],
        )
        reasons = {
            candidate.artifact.artifact_id: candidate.selection_reason
            for candidate in guarded.dropped_candidates
        }
        self.assertEqual(
            reasons["tenant-mismatch"], ContextSelectionReason.DROPPED_TENANT_MISMATCH
        )
        self.assertEqual(reasons["blocked"], ContextSelectionReason.DROPPED_GUARD)
        self.assertEqual(
            reasons["global-memory"], ContextSelectionReason.DROPPED_POLICY
        )

        ranked = await DefaultContextRanker().rank(
            _request(),
            [
                _candidate(artifact_id="recent", lane="recent_turn", score=0.0),
                _candidate(
                    artifact_id="system", lane="system_persona_policy", score=0.0
                ),
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
        registry.set_policy_resolver("resolver", owner="owner-a")
        registry.set_state_store("store", owner="owner-a")
        registry.set_memory_writer("writer", owner="owner-a")
        registry.set_cache("cache", owner="owner-a")
        registry.set_commit_store("commit-store", owner="owner-a")
        registry.register_renderer(
            StructuredLaneRenderer(
                render_class="system_persona_policy_items",
                lane="system_persona_policy",
            ),
            owner="owner-a",
        )
        registry.register_renderer(RecentTurnMessageRenderer(), owner="owner-a")
        self.assertEqual(registry.contributors, ["contributor"])
        self.assertEqual(registry.guards, ["guard"])
        self.assertEqual(registry.rankers, ["ranker"])
        self.assertEqual(registry.trace_sinks, ["trace"])
        self.assertEqual(registry.policy_resolver, "resolver")
        self.assertEqual(registry.state_store, "store")
        self.assertEqual(registry.memory_writer, "writer")
        self.assertEqual(registry.cache, "cache")
        self.assertEqual(registry.commit_store, "commit-store")
        self.assertEqual(len(registry.renderers), 2)
        self.assertEqual(
            ContextComponentRegistry._owner_name(  # pylint: disable=protected-access
                owner=None,
                value=object(),
            ),
            "builtins.object",
        )
        with self.assertRaisesRegex(
            RuntimeError, "already has 'policy_resolver' owned"
        ):
            registry.set_policy_resolver("other", owner="owner-b")
        with self.assertRaisesRegex(RuntimeError, "already has renderer"):
            registry.register_renderer(
                StructuredLaneRenderer(
                    render_class="system_persona_policy_items",
                    lane="system_persona_policy",
                ),
                owner="owner-b",
            )
        with self.assertRaisesRegex(RuntimeError, "require render_class"):
            registry.register_renderer(
                SimpleNamespace(render_class=" "),
                owner="owner-a",
            )

        policy = _policy()
        request = _request(
            ingress_metadata={
                "tenant_resolution": {"mode": "resolved", "source": "test"}
            }
        )

        persona_candidates = await PersonaPolicyContributor().collect(
            request,
            policy=_policy(persona="Be concise."),
            state=None,
        )
        self.assertEqual(
            persona_candidates[0].artifact.content["persona"], "Be concise."
        )
        self.assertEqual(
            persona_candidates[0].artifact.render_class,
            "system_persona_policy_items",
        )
        self.assertEqual(
            persona_candidates[0].artifact.provenance.source.source_key,
            "default",
        )

        self.assertEqual(
            await StateContributor().collect(request, policy=policy, state=None), []
        )
        state_candidates = await StateContributor().collect(
            request, policy=policy, state=_state()
        )
        self.assertEqual(state_candidates[0].artifact.lane, "bounded_control_state")
        self.assertEqual(
            state_candidates[0].artifact.render_class,
            "bounded_control_state_items",
        )

        event_log_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        id=1, role="assistant", content="second", trace_id="trace-2"
                    ),
                    SimpleNamespace(
                        id=2, role="user", content="first", trace_id="trace-1"
                    ),
                ]
            )
        )
        recent_candidates = await RecentTurnContributor(
            event_log_service=event_log_service
        ).collect(request, policy=policy, state=None)
        self.assertEqual(
            [c.artifact.content["content"] for c in recent_candidates],
            ["first", "second"],
        )
        self.assertEqual(
            recent_candidates[0].artifact.render_class,
            "recent_turn_messages",
        )

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
        self.assertTrue(
            knowledge_candidates[0].artifact.content["excerpt"].endswith("...")
        )
        self.assertEqual(
            knowledge_candidates[0].artifact.render_class, "evidence_items"
        )

        conversation_state_service = SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        status="open",
                        service_route_key="valet.customer_inbox",
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
            channel_candidates[0].artifact.content["conversation"][
                "service_route_key"
            ],
            "valet.customer_inbox",
        )
        self.assertEqual(
            await ChannelOrchestrationContributor(
                conversation_state_service=SimpleNamespace(
                    list=AsyncMock(return_value=[])
                ),
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
                conversation_state_service=SimpleNamespace(
                    list=AsyncMock(return_value=[])
                ),
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
        self.assertEqual(
            await ops_case.collect(_request(), policy=policy, state=None), []
        )
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
            ).collect(
                _request(scope=_scope(case_id=case_id)), policy=policy, state=None
            ),
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
        audit_candidates = await AuditContributor(
            audit_trace_service=audit_service
        ).collect(
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
            await memory_contributor.collect(
                request, policy=_policy(allow_long_term_memory=False), state=None
            ),
            [],
        )
        kept_memory = await memory_contributor.collect(
            request, policy=policy, state=None
        )
        self.assertEqual(len(kept_memory), 2)
        global_request = _request(
            scope=_scope(
                tenant_id=str(GLOBAL_TENANT_ID),
                sender_id="user-1",
                conversation_id="room-1",
            )
        )
        global_kept = await memory_contributor.collect(
            global_request, policy=policy, state=None
        )
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

    async def test_renderers_and_commit_store_cover_new_runtime_collaborators(
        self,
    ) -> None:
        structured_messages = await StructuredLaneRenderer(
            render_class="evidence_items",
            lane="evidence",
        ).render(
            _request(),
            [_candidate(artifact_id="e1", lane="evidence", content={"x": 1})],
            policy=_policy(),
        )
        self.assertEqual(structured_messages[0].content["context_lane"], "evidence")

        recent_messages = await RecentTurnMessageRenderer().render(
            _request(),
            [
                ContextCandidate(
                    artifact=ContextArtifact(
                        artifact_id="recent-1",
                        lane="recent_turn",
                        kind="recent_turn",
                        render_class="recent_turn_messages",
                        content={"role": "assistant", "content": "hello"},
                        provenance=ContextProvenance(
                            contributor="recent_turns",
                            source_kind="event_log",
                            tenant_id=str(_tenant_uuid()),
                        ),
                    ),
                    contributor="recent_turns",
                )
            ],
            policy=_policy(),
        )
        self.assertEqual(recent_messages[0].content, "hello")

        class _LedgerService:
            def __init__(self) -> None:
                self.rows: dict[str, SimpleNamespace] = {}

            async def create(self, payload):
                row = SimpleNamespace(
                    id=uuid.uuid4(),
                    row_version=1,
                    **payload,
                )
                self.rows[payload["commit_token"]] = row
                return row

            async def get(self, where):
                return self.rows.get(where["commit_token"])

            async def update_with_row_version(
                self, where, *, expected_row_version, changes
            ):
                for row in self.rows.values():
                    if row.id != where["id"] or row.tenant_id != where["tenant_id"]:
                        continue
                    if row.row_version != expected_row_version:
                        return None
                    for key, value in changes.items():
                        setattr(row, key, value)
                    row.row_version += 1
                    return row
                return None

            async def update(self, where, changes):
                for row in self.rows.values():
                    if row.id != where["id"] or row.tenant_id != where["tenant_id"]:
                        continue
                    for key, value in changes.items():
                        setattr(row, key, value)
                    row.row_version += 1
                    return row
                return None

        ledger_service = _LedgerService()
        commit_store = RelationalContextCommitStore(ledger_service=ledger_service)
        request = _request()
        token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="prepared-fp",
            ttl_seconds=30,
        )
        prepared = PreparedContextTurn(
            completion_request=CompletionRequest(
                messages=[CompletionMessage(role="user", content="hello")]
            ),
            bundle=ContextBundle(
                policy=_policy(),
                state=None,
                selected_candidates=(),
                dropped_candidates=(),
                prefix_fingerprint="prefix-1",
                cache_hints={},
                trace={},
            ),
            state_handle=runtime_module.scope_key(request.scope),
            commit_token=token,
            trace={},
        )
        begin = await commit_store.begin_commit(
            request=request,
            prepared=prepared,
            prepared_fingerprint="prepared-fp",
        )
        self.assertEqual(begin.state, ContextCommitState.COMMITTING)
        result = ContextCommitResult(commit_token=token, state_revision=4)
        await commit_store.complete_commit(
            request=request,
            prepared=prepared,
            prepared_fingerprint="prepared-fp",
            result=result,
        )
        await commit_store.complete_commit(
            request=request,
            prepared=prepared,
            prepared_fingerprint="prepared-fp",
            result=result,
        )
        replay = await commit_store.begin_commit(
            request=request,
            prepared=prepared,
            prepared_fingerprint="prepared-fp",
        )
        self.assertEqual(replay.state, ContextCommitState.COMMITTED)
        self.assertEqual(replay.replay_result, result)

        failed_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="prepared-fp-2",
            ttl_seconds=30,
        )
        failed_prepared = PreparedContextTurn(
            completion_request=prepared.completion_request,
            bundle=prepared.bundle,
            state_handle=prepared.state_handle,
            commit_token=failed_token,
            trace={},
        )
        await commit_store.fail_commit(
            request=request,
            prepared=failed_prepared,
            prepared_fingerprint="prepared-fp-2",
            error_message="boom",
        )
        with self.assertRaisesRegex(RuntimeError, "previous commit failed"):
            await commit_store.begin_commit(
                request=request,
                prepared=failed_prepared,
                prepared_fingerprint="prepared-fp-2",
            )

    async def test_runtime_helper_and_commit_store_edge_paths(self) -> None:
        rsg = Mock()
        self.assertEqual(
            runtime_module.ContextStateSnapshotService(
                table="context_state_snapshot",
                rsg=rsg,
            ).table,
            "context_state_snapshot",
        )
        self.assertEqual(
            runtime_module.ContextEventLogService(
                table="context_event_log",
                rsg=rsg,
            ).table,
            "context_event_log",
        )
        self.assertEqual(
            runtime_module.ContextMemoryRecordService(
                table="context_memory_record",
                rsg=rsg,
            ).table,
            "context_memory_record",
        )
        self.assertEqual(
            runtime_module.ContextCacheRecordService(
                table="context_cache_record",
                rsg=rsg,
            ).table,
            "context_cache_record",
        )
        self.assertEqual(
            runtime_module.ContextCommitLedgerService(
                table="context_commit_ledger",
                rsg=rsg,
            ).table,
            "context_commit_ledger",
        )
        self.assertEqual(
            runtime_module.ContextTraceService(
                table="context_trace",
                rsg=rsg,
            ).table,
            "context_trace",
        )

        source_ref = ContextSourceRef(
            kind="knowledge",
            source_key="kb-main",
            source_id="doc-1",
            canonical_locator="https://example.invalid/doc-1",
            metadata={"rank": 1},
        )
        self.assertEqual(
            runtime_module._serialize_source_ref(
                source_ref
            ),  # pylint: disable=protected-access
            {
                "kind": "knowledge",
                "source_key": "kb-main",
                "source_id": "doc-1",
                "canonical_locator": "https://example.invalid/doc-1",
                "segment_id": None,
                "locale": None,
                "category": None,
                "metadata": {"rank": 1},
            },
        )
        self.assertIsNone(
            runtime_module._deserialize_source_ref(
                None
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(
            runtime_module._deserialize_source_ref(  # pylint: disable=protected-access
                {"kind": " "}
            )
        )
        restored_source = (
            runtime_module._deserialize_source_ref(  # pylint: disable=protected-access
                {
                    "kind": "knowledge",
                    "source_key": "kb-main",
                    "source_id": "doc-1",
                    "canonical_locator": "https://example.invalid/doc-1",
                    "metadata": {"rank": 1},
                }
            )
        )
        self.assertEqual(
            restored_source.canonical_locator, source_ref.canonical_locator
        )
        restored_provenance = (
            runtime_module._deserialize_provenance(  # pylint: disable=protected-access
                None
            )
        )
        self.assertEqual(restored_provenance.contributor, "context_engine")
        with self.assertRaisesRegex(RuntimeError, "missing write_type"):
            runtime_module._deserialize_memory_write(
                {}
            )  # pylint: disable=protected-access
        valid_memory_write = runtime_module._deserialize_memory_write(
            {
                "write_type": MemoryWriteType.FACT.value,
                "content": {"statement": "prefers tea"},
                "provenance": {
                    "contributor": "context_engine",
                    "source_kind": "turn_commit",
                },
                "scope_partition": {"sender_id": "user-1"},
                "tags": ["preference"],
            }
        )  # pylint: disable=protected-access
        self.assertEqual(valid_memory_write.write_type, MemoryWriteType.FACT)
        serialized_result = (
            runtime_module._serialize_commit_result(  # pylint: disable=protected-access
                ContextCommitResult(commit_token="commit-1", state_revision=1)
            )
        )
        deserialized_result = runtime_module._deserialize_commit_result(
            serialized_result
        )  # pylint: disable=protected-access
        self.assertEqual(
            deserialized_result.commit_token,
            "commit-1",
        )
        with self.assertRaisesRegex(RuntimeError, "missing commit_token"):
            runtime_module._deserialize_commit_result(
                {}
            )  # pylint: disable=protected-access
        trace_payload, selected_items, dropped_items = (
            runtime_module._trace_payload_for_policy(
                {
                    "scope": {"tenant_id": str(_tenant_uuid())},
                    "selected": [{"artifact_id": "selected-1"}],
                    "dropped": [{"artifact_id": "dropped-1"}],
                },
                policy=ContextPolicy(
                    trace_capture_selected=False,
                    trace_capture_dropped=False,
                ),
            )  # pylint: disable=protected-access
        )
        self.assertEqual(trace_payload, {"scope": {"tenant_id": str(_tenant_uuid())}})
        self.assertIsNone(selected_items)
        self.assertIsNone(dropped_items)

        structured_renderer = StructuredLaneRenderer(
            render_class="evidence_items",
            lane="evidence",
        )
        self.assertEqual(
            await structured_renderer.render(_request(), [], policy=_policy()),
            [],
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected lane"):
            await structured_renderer.render(
                _request(),
                [_candidate(artifact_id="wrong-lane", lane="recent_turn")],
                policy=_policy(),
            )

        def _recent_candidate(content) -> ContextCandidate:
            return ContextCandidate(
                artifact=ContextArtifact(
                    artifact_id="recent-edge",
                    lane="recent_turn",
                    kind="recent_turn",
                    render_class="recent_turn_messages",
                    content=content,
                    provenance=ContextProvenance(
                        contributor="recent_turns",
                        source_kind="event_log",
                        tenant_id=str(_tenant_uuid()),
                    ),
                ),
                contributor="recent_turns",
            )

        recent_renderer = RecentTurnMessageRenderer()
        with self.assertRaisesRegex(RuntimeError, "dict content"):
            await recent_renderer.render(
                _request(),
                [_recent_candidate("bad")],
                policy=_policy(),
            )
        with self.assertRaisesRegex(RuntimeError, "string role"):
            await recent_renderer.render(
                _request(),
                [_recent_candidate({"content": "hello"})],
                policy=_policy(),
            )
        with self.assertRaisesRegex(RuntimeError, "string, object, list, or null"):
            await recent_renderer.render(
                _request(),
                [_recent_candidate({"role": "assistant", "content": 123})],
                policy=_policy(),
            )

        class _EdgeLedgerService:
            def __init__(self, *, return_none_on_update: bool = False) -> None:
                self.return_none_on_update = return_none_on_update
                self.rows: dict[str, SimpleNamespace] = {}

            async def create(self, payload):
                row = SimpleNamespace(
                    id=uuid.uuid4(),
                    row_version=1,
                    **payload,
                )
                self.rows[payload["commit_token"]] = row
                return row

            async def get(self, where):
                return self.rows.get(where["commit_token"])

            async def update_with_row_version(
                self,
                where,
                *,
                expected_row_version,
                changes,
            ):
                if self.return_none_on_update:
                    return None
                for row in self.rows.values():
                    if row.id != where["id"] or row.tenant_id != where["tenant_id"]:
                        continue
                    if row.row_version != expected_row_version:
                        return None
                    for key, value in changes.items():
                        setattr(row, key, value)
                    row.row_version += 1
                    return row
                return None

            async def update(self, where, changes):
                if self.return_none_on_update:
                    return None
                for row in self.rows.values():
                    if row.id != where["id"] or row.tenant_id != where["tenant_id"]:
                        continue
                    for key, value in changes.items():
                        setattr(row, key, value)
                    row.row_version += 1
                    return row
                return None

        request = _request()

        def _prepared_for(
            commit_token: str,
            *,
            scope: ContextScope | None = None,
            state_handle: str | None = None,
        ) -> PreparedContextTurn:
            prepared_scope = scope or request.scope
            return PreparedContextTurn(
                completion_request=CompletionRequest(
                    messages=[CompletionMessage(role="user", content="hello")]
                ),
                bundle=ContextBundle(
                    policy=_policy(),
                    state=None,
                    selected_candidates=(),
                    dropped_candidates=(),
                    prefix_fingerprint="prefix-1",
                    cache_hints={},
                    trace={},
                ),
                state_handle=state_handle or runtime_module.scope_key(prepared_scope),
                commit_token=commit_token,
                trace={},
            )

        commit_store = RelationalContextCommitStore(ledger_service=_EdgeLedgerService())
        with self.assertRaisesRegex(RuntimeError, "^Invalid context commit token\\.$"):
            await commit_store.begin_commit(
                request=request,
                prepared=_prepared_for("missing-token"),
                prepared_fingerprint="fp-missing-token",
            )
        missing_result_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-missing-result",
            ttl_seconds=30,
        )
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            missing_result_token
        ].commit_state = ContextCommitState.COMMITTED.value
        with self.assertRaisesRegex(RuntimeError, "committed result missing"):
            await commit_store.begin_commit(
                request=request,
                prepared=_prepared_for(missing_result_token),
                prepared_fingerprint="fp-missing-result",
            )

        in_progress_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-in-progress",
            ttl_seconds=30,
        )
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            in_progress_token
        ].commit_state = ContextCommitState.COMMITTING.value
        with self.assertRaisesRegex(RuntimeError, "already in progress"):
            await commit_store.begin_commit(
                request=request,
                prepared=_prepared_for(in_progress_token),
                prepared_fingerprint="fp-in-progress",
            )

        scope_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-scope",
            ttl_seconds=30,
        )
        with self.assertRaisesRegex(RuntimeError, "scope mismatch"):
            await commit_store.begin_commit(
                request=_request(scope=_scope(conversation_id="room-2")),
                prepared=_prepared_for(scope_token),
                prepared_fingerprint="fp-scope",
            )

        state_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-state",
            ttl_seconds=30,
        )
        with self.assertRaisesRegex(RuntimeError, "prepared state mismatch"):
            await commit_store.begin_commit(
                request=request,
                prepared=_prepared_for(
                    state_token,
                    state_handle="wrong-state",
                ),
                prepared_fingerprint="fp-state",
            )

        prepared_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-prepared",
            ttl_seconds=30,
        )
        with self.assertRaisesRegex(RuntimeError, "prepared mismatch"):
            await commit_store.begin_commit(
                request=request,
                prepared=_prepared_for(prepared_token),
                prepared_fingerprint="wrong-fingerprint",
            )

        expired_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-expired",
            ttl_seconds=30,
        )
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            expired_token
        ].expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        with self.assertRaisesRegex(RuntimeError, "expired"):
            await commit_store.begin_commit(
                request=request,
                prepared=_prepared_for(expired_token),
                prepared_fingerprint="fp-expired",
            )
        expired_row = commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            expired_token
        ]
        self.assertEqual(
            expired_row.commit_state,
            ContextCommitState.FAILED.value,
        )
        self.assertEqual(
            expired_row.last_error,
            "expired",
        )

        await commit_store.fail_commit(
            request=request,
            prepared=_prepared_for("missing-token"),
            prepared_fingerprint="fp-missing-token",
            error_message="boom",
        )

        committed_fail_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-committed-fail",
            ttl_seconds=30,
        )
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            committed_fail_token
        ].commit_state = ContextCommitState.COMMITTED.value
        await commit_store.fail_commit(
            request=request,
            prepared=_prepared_for(committed_fail_token),
            prepared_fingerprint="fp-committed-fail",
            error_message="boom",
        )

        already_committed_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-already-committed",
            ttl_seconds=30,
        )
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            already_committed_token
        ].commit_state = ContextCommitState.COMMITTED.value
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            already_committed_token
        ].result_json = runtime_module._serialize_commit_result(
            ContextCommitResult(
                commit_token=already_committed_token,
                state_revision=1,
            )
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "already committed"):
            await commit_store.complete_commit(
                request=request,
                prepared=_prepared_for(already_committed_token),
                prepared_fingerprint="fp-already-committed",
                result=ContextCommitResult(
                    commit_token=already_committed_token,
                    state_revision=2,
                ),
            )

        not_in_progress_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-not-in-progress",
            ttl_seconds=30,
        )
        with self.assertRaisesRegex(RuntimeError, "commit not in progress"):
            await commit_store.complete_commit(
                request=request,
                prepared=_prepared_for(not_in_progress_token),
                prepared_fingerprint="fp-not-in-progress",
                result=ContextCommitResult(
                    commit_token=not_in_progress_token,
                    state_revision=3,
                ),
            )

        expired_committed_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-expired-committed",
            ttl_seconds=30,
        )
        expired_result = ContextCommitResult(
            commit_token=expired_committed_token,
            state_revision=4,
        )
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            expired_committed_token
        ].commit_state = ContextCommitState.COMMITTED.value
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            expired_committed_token
        ].result_json = runtime_module._serialize_commit_result(
            expired_result
        )  # pylint: disable=protected-access
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            expired_committed_token
        ].expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        with self.assertRaisesRegex(RuntimeError, "expired"):
            await commit_store.complete_commit(
                request=request,
                prepared=_prepared_for(expired_committed_token),
                prepared_fingerprint="fp-expired-committed",
                result=expired_result,
            )
        replayable_expired_token = await commit_store.issue_token(
            request=request,
            prepared_fingerprint="fp-replayable-expired",
            ttl_seconds=30,
        )
        replayable_result = ContextCommitResult(
            commit_token=replayable_expired_token,
            state_revision=6,
        )
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            replayable_expired_token
        ].commit_state = ContextCommitState.COMMITTED.value
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            replayable_expired_token
        ].result_json = runtime_module._serialize_commit_result(
            replayable_result
        )  # pylint: disable=protected-access
        commit_store._ledger_service.rows[  # type: ignore[attr-defined]
            replayable_expired_token
        ].expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        replay = await commit_store.begin_commit(
            request=request,
            prepared=_prepared_for(replayable_expired_token),
            prepared_fingerprint="fp-replayable-expired",
        )
        self.assertEqual(replay.replay_result, replayable_result)

        transition_store = RelationalContextCommitStore(
            ledger_service=_EdgeLedgerService(return_none_on_update=True)
        )
        transition_token = await transition_store.issue_token(
            request=request,
            prepared_fingerprint="fp-transition",
            ttl_seconds=30,
        )
        with self.assertRaisesRegex(RuntimeError, "transition failed"):
            await transition_store.begin_commit(
                request=request,
                prepared=_prepared_for(transition_token),
                prepared_fingerprint="fp-transition",
            )

        finalize_store = RelationalContextCommitStore(
            ledger_service=_EdgeLedgerService(return_none_on_update=True)
        )
        finalize_token = await finalize_store.issue_token(
            request=request,
            prepared_fingerprint="fp-finalize",
            ttl_seconds=30,
        )
        finalize_store._ledger_service.rows[  # type: ignore[attr-defined]
            finalize_token
        ].commit_state = ContextCommitState.COMMITTING.value
        with self.assertRaisesRegex(RuntimeError, "finalize failed"):
            await finalize_store.complete_commit(
                request=request,
                prepared=_prepared_for(finalize_token),
                prepared_fingerprint="fp-finalize",
                result=ContextCommitResult(
                    commit_token=finalize_token,
                    state_revision=5,
                ),
            )

        self.assertIsNone(
            await commit_store._update_row(  # pylint: disable=protected-access
                row=SimpleNamespace(
                    id=None,
                    tenant_id=_tenant_uuid(),
                    row_version=1,
                ),
                changes={"commit_state": ContextCommitState.FAILED.value},
            )
        )
        fallback_service = SimpleNamespace(update=AsyncMock(return_value="updated"))
        fallback_store = RelationalContextCommitStore(ledger_service=fallback_service)
        self.assertEqual(
            await fallback_store._update_row(  # pylint: disable=protected-access
                row=SimpleNamespace(
                    id=uuid.uuid4(),
                    tenant_id=_tenant_uuid(),
                ),
                changes={"commit_state": ContextCommitState.COMMITTING.value},
            ),
            "updated",
        )
        fallback_service.update.assert_awaited_once()
        self.assertIsNone(
            commit_store._expires_at(0)
        )  # pylint: disable=protected-access
