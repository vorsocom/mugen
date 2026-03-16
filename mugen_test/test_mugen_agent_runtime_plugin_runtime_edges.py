"""Edge and coverage tests for agent_runtime plugin runtime adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.contract.agent import (
    AgentRuntimePolicy,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityResult,
    EvaluationRequest,
    EvaluationStatus,
    JoinPolicy,
    JoinState,
    PlanDecision,
    PlanDecisionKind,
    PlanLease,
    PlanObservation,
    PlanOutcome,
    PlanOutcomeStatus,
    PlanRunCursor,
    PlanRunLineage,
    PlanRunMode,
    PlanRunRequest,
    PlanRunState,
    PlanRunStatus,
    PlanRunStep,
    PlanRunStepKind,
    PreparedPlanRun,
)
from mugen.core.contract.context import (
    ContextBundle,
    ContextPolicy,
    ContextScope,
    ContextState,
    PreparedContextTurn,
)
from mugen.core.contract.gateway.completion import (
    CompletionMessage,
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
)
from mugen.core.plugin.agent_runtime.service.registry import AgentComponentRegistry
import mugen.core.plugin.agent_runtime.service.runtime as runtime_module
from mugen.core.plugin.agent_runtime.service.runtime import (
    ACPActionCapabilityProvider,
    AgentPlanRunService,
    AgentPlanStepService,
    AllowlistExecutionGuard,
    CodeConfiguredAgentPolicyResolver,
    LLMEvaluationStrategy,
    LLMPlannerStrategy,
    RelationalPlanRunStore,
    TextResponseSynthesizer,
)


def _scope(*, sender_id: str | None = "22222222-2222-2222-2222-222222222222") -> ContextScope:
    return ContextScope(
        tenant_id="11111111-1111-1111-1111-111111111111",
        platform="matrix",
        channel_id="matrix",
        room_id="room-1",
        sender_id=sender_id,
        conversation_id="room-1",
    )


def _prepared_context() -> PreparedContextTurn:
    return PreparedContextTurn(
        completion_request=CompletionRequest(
            messages=[
                CompletionMessage(role="system", content="Be helpful."),
                CompletionMessage(role="user", content="hello"),
            ],
            operation="completion",
            model="test-model",
            vendor_params={"seed": "base"},
        ),
        bundle=ContextBundle(
            policy=ContextPolicy(),
            state=ContextState(revision=1),
            selected_candidates=(),
            dropped_candidates=(),
        ),
        state_handle="state-1",
        commit_token="commit-1",
        trace={},
    )


def _request(
    *,
    mode: PlanRunMode = PlanRunMode.CURRENT_TURN,
    prepared_context: PreparedContextTurn | None = None,
    available_capabilities: tuple[CapabilityDescriptor, ...] = (),
    metadata: dict | None = None,
    service_route_key: str | None = "support.primary",
    agent_key: str | None = None,
    sender_id: str | None = "22222222-2222-2222-2222-222222222222",
) -> PlanRunRequest:
    return PlanRunRequest(
        mode=mode,
        scope=_scope(sender_id=sender_id),
        user_message="Handle the request",
        service_route_key=service_route_key,
        agent_key=agent_key,
        prepared_context=prepared_context,
        available_capabilities=available_capabilities,
        metadata=dict(metadata or {}),
        ingress_metadata={"service_route_key": service_route_key}
        if service_route_key is not None
        else {},
    )


def _run(
    *,
    request: PlanRunRequest | None = None,
    run_id: str = "run-1",
    status: PlanRunStatus = PlanRunStatus.PREPARED,
    policy: AgentRuntimePolicy | None = None,
    lease: PlanLease | None = None,
    final_outcome: PlanOutcome | None = None,
) -> PreparedPlanRun:
    resolved_request = request or _request()
    now = datetime.now(timezone.utc)
    return PreparedPlanRun(
        run_id=run_id,
        mode=resolved_request.mode,
        status=status,
        state=PlanRunState(goal=resolved_request.user_message, status=status),
        policy=policy
        or AgentRuntimePolicy(
            enabled=True,
            current_turn_enabled=True,
            background_enabled=True,
        ),
        request_snapshot=runtime_module._request_snapshot(resolved_request),  # pylint: disable=protected-access
        cursor=PlanRunCursor(run_id=run_id, status=status),
        service_route_key=resolved_request.service_route_key,
        lease=lease,
        final_outcome=final_outcome,
        created_at=now,
        updated_at=now,
        row_version=1,
        metadata={"trace": "1"},
    )


class _FakeRunService:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, SimpleNamespace] = {}

    async def create(self, payload: dict) -> SimpleNamespace:
        now = datetime.now(timezone.utc)
        row = SimpleNamespace(
            id=uuid.uuid4(),
            created_at=now,
            updated_at=now,
            row_version=1,
            **payload,
        )
        self.rows[row.id] = row
        return row

    async def get(self, where: dict) -> SimpleNamespace | None:
        return self.rows.get(where["id"])

    async def update_with_row_version(
        self,
        where: dict,
        *,
        expected_row_version: int | None,
        changes: dict,
    ) -> SimpleNamespace | None:
        row = self.rows.get(where["id"])
        if row is None:
            return None
        if expected_row_version is not None and row.row_version != expected_row_version:
            return None
        for key, value in changes.items():
            setattr(row, key, value)
        row.row_version = int(row.row_version or 0) + 1
        row.updated_at = datetime.now(timezone.utc)
        return row

    async def list(self, *, filter_groups=None, order_by=None, limit=None) -> list:
        rows = list(self.rows.values())
        for filter_group in filter_groups or []:
            where = dict(getattr(filter_group, "where", {}) or {})
            rows = [
                row
                for row in rows
                if all(getattr(row, key) == value for key, value in where.items())
            ]
        for order in reversed(order_by or []):
            field = getattr(order, "field", None)
            rows.sort(key=lambda row: getattr(row, field))
        if limit is not None:
            rows = rows[:limit]
        return rows


class _FakeStepService:
    def __init__(self) -> None:
        self.rows: list[SimpleNamespace] = []

    async def create(self, payload: dict) -> SimpleNamespace:
        row = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            **payload,
        )
        self.rows.append(row)
        return row

    async def list(self, *, filter_groups=None, order_by=None, limit=None) -> list:
        rows = list(self.rows)
        for filter_group in filter_groups or []:
            where = dict(getattr(filter_group, "where", {}) or {})
            rows = [
                row
                for row in rows
                if all(getattr(row, key) == value for key, value in where.items())
            ]
        for order in reversed(order_by or []):
            field = getattr(order, "field", None)
            rows.sort(key=lambda row: getattr(row, field))
        if limit is not None:
            rows = rows[:limit]
        return rows


class _ActionSchema:
    @classmethod
    def model_json_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        }

    @classmethod
    def model_validate(cls, arguments: dict) -> dict:
        return {"validated": True, **arguments}


class _FailingSchema(_ActionSchema):
    @classmethod
    def model_validate(cls, arguments: dict) -> dict:
        raise ValueError("bad payload")


class _FallbackSchema:
    @classmethod
    def model_validate(cls, arguments: dict) -> dict:
        return dict(arguments)


class _SchemaWithEntityRequired(_ActionSchema):
    @classmethod
    def model_json_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "format": "uuid"},
                "note": {"type": "string"},
            },
            "required": ["entity_id", "note"],
        }


class _ACPService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action_update(
        self,
        *,
        tenant_id,
        entity_id,
        where,
        auth_user_id,
        data,
    ):
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "where": where,
                "auth_user_id": auth_user_id,
                "data": data,
            }
        )
        return {"status": "updated", "data": data}, 202

    async def action_status(
        self,
        *,
        tenant_id,
        where,
        data,
    ):
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "where": where,
                "data": data,
            }
        )
        return {"status": "failed"}, 500

    async def action_raise(self, *, data):
        _ = data
        raise RuntimeError("boom")

    async def action_auth_only(self, *, auth_user_id, data):
        return {"auth_user_id": auth_user_id, "data": data}

    async def action_plain(self, *, tenant_id, where):
        self.calls.append({"tenant_id": tenant_id, "where": where})
        return {"status": "plain"}


class _AdminRegistry:
    def __init__(self, *, resources: dict[str, SimpleNamespace], services: dict[str, object]) -> None:
        self.resources = resources
        self._services = services

    def get_edm_service(self, service_key: str):
        return self._services[service_key]

    def get_resource(self, entity_set: str):
        for resource in self.resources.values():
            if resource.entity_set == entity_set:
                return resource
        raise KeyError(entity_set)


class TestMugenAgentRuntimePluginRuntimeEdges(unittest.IsolatedAsyncioTestCase):
    async def test_registry_and_helper_functions_cover_runtime_branches(self) -> None:
        registry = AgentComponentRegistry()
        policy_resolver = object()
        scheduler = object()

        registry.set_policy_resolver(policy_resolver)
        registry.set_scheduler(scheduler, owner=" plugin.scheduler ")
        registry.set_scheduler(scheduler, owner="plugin.scheduler")

        self.assertIs(registry.policy_resolver, policy_resolver)
        self.assertIs(registry.scheduler, scheduler)
        self.assertIn("object", registry._single_slot_owners["policy_resolver"])  # pylint: disable=protected-access
        self.assertEqual(
            registry._single_slot_owners["scheduler"],  # pylint: disable=protected-access
            "plugin.scheduler",
        )

        request = _request()
        completion = CompletionResponse(
            content={"answer": 42},
            model="gpt-test",
            stop_reason="done",
            message={"role": "assistant"},
            tool_calls=[{"id": "call-1"}],
            usage=CompletionUsage(
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                vendor_fields={"cost": 0.1},
            ),
            vendor_fields={"trace": "1"},
        )
        policy = AgentRuntimePolicy(
            enabled=True,
            current_turn_enabled=True,
            background_enabled=True,
            capability_allow=("cap.lookup",),
            metadata={"trace": "1"},
        )
        state = PlanRunState(
            goal="Handle the request",
            last_response_text="hello",
            last_error="warning",
            summary="summary",
            metadata={"trace": "1"},
        )
        outcome = PlanOutcome(
            status=PlanOutcomeStatus.SPAWNED_BACKGROUND,
            final_user_responses=({"type": "text", "content": "queued"},),
            assistant_response="queued",
            completion=completion,
            background_run_id="run-bg",
            error_message="temporary",
            metadata={"trace": "1"},
        )
        descriptor = CapabilityDescriptor(
            key="cap.lookup",
            title="Lookup",
            description="Lookup data",
            input_schema={"type": "object"},
        )
        lineage = PlanRunLineage(
            parent_run_id="run-parent",
            root_run_id="run-root",
            spawned_by_step_no=2,
            agent_key="specialist.lookup",
        )
        join_policy = JoinPolicy(
            on_required_child_failed=PlanOutcomeStatus.FAILED,
            on_required_child_handoff=PlanOutcomeStatus.HANDOFF,
            on_required_child_stopped=PlanOutcomeStatus.STOPPED,
        )
        join_state = JoinState(
            child_run_ids=("child-1",),
            required_child_run_ids=("child-1",),
            completed_child_run_ids=("child-1",),
            last_joined_sequence_no=2,
            timeout_at=datetime.now(timezone.utc),
            policy=join_policy,
            metadata={"trace": "1"},
        )
        tool_invocations = runtime_module._tool_call_invocations(  # pylint: disable=protected-access
            [
                {
                    "id": "call-1",
                    "function": {
                        "name": "cap.lookup",
                        "arguments": '{"query": "abc"}',
                    },
                },
                {
                    "id": "call-2",
                    "name": "cap.other",
                    "arguments": "not-json",
                },
                {"id": "call-3", "name": " ", "arguments": {"ignored": True}},
            ]
        )

        self.assertIn("*", runtime_module._scope_key(_scope(sender_id=None)))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._scope_to_dict(_scope())["tenant_id"],
            _scope().tenant_id,
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._request_snapshot(request)["service_route_key"],
            "support.primary",
        )
        self.assertIsNone(runtime_module._serialize_lineage(None))  # pylint: disable=protected-access
        self.assertIsNone(runtime_module._deserialize_lineage(None))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._deserialize_lineage(
                runtime_module._serialize_lineage(lineage)  # pylint: disable=protected-access
            ).agent_key,
            "specialist.lookup",
        )
        self.assertIsNone(runtime_module._serialize_join_policy(None))  # pylint: disable=protected-access
        self.assertIsNone(runtime_module._deserialize_join_policy(None))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._deserialize_join_policy(
                runtime_module._serialize_join_policy(join_policy)  # pylint: disable=protected-access
            ).on_required_child_failed,
            PlanOutcomeStatus.FAILED,
        )
        self.assertIsNone(runtime_module._serialize_join_state(None))  # pylint: disable=protected-access
        self.assertIsNone(runtime_module._deserialize_join_state(None))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._deserialize_join_state(
                runtime_module._serialize_join_state(join_state)  # pylint: disable=protected-access
            ).last_joined_sequence_no,
            2,
        )
        self.assertTrue(runtime_module._serialize_policy(policy)["enabled"])  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._deserialize_policy({"planner_key": "x"}).planner_key,
            "x",
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._serialize_state(state)["summary"],
            "summary",
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._deserialize_state({"goal": "g", "status": "active"}).status,
            PlanRunStatus.ACTIVE,
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._serialize_outcome(outcome)["background_run_id"],
            "run-bg",
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._deserialize_outcome({"status": "completed"}).status,
            PlanOutcomeStatus.COMPLETED,
        )
        serialized_completion = runtime_module._serialize_completion(completion)  # pylint: disable=protected-access
        self.assertEqual(serialized_completion["usage"]["total_tokens"], 3)
        self.assertIsNone(runtime_module._serialize_completion(None))  # pylint: disable=protected-access
        self.assertIsNone(
            runtime_module._serialize_completion(CompletionResponse(content="hello"))["usage"]  # pylint: disable=protected-access
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._deserialize_completion(serialized_completion).usage.total_tokens,
            3,
        )
        self.assertIsNone(runtime_module._deserialize_completion(None))  # pylint: disable=protected-access
        self.assertIsNone(  # pylint: disable=protected-access
            runtime_module._deserialize_completion({"content": "hello", "usage": "oops"}).usage
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._parse_json_object('{"ok": true}')["ok"],
            True,
        )
        self.assertIsNone(runtime_module._parse_json_object("[1]"))  # pylint: disable=protected-access
        self.assertIsNone(runtime_module._parse_json_object(""))  # pylint: disable=protected-access
        self.assertIsNone(runtime_module._parse_json_object(None))  # pylint: disable=protected-access
        self.assertEqual(runtime_module._coerce_to_text("hi"), "hi")  # pylint: disable=protected-access
        self.assertEqual(runtime_module._coerce_to_text(None), "")  # pylint: disable=protected-access
        self.assertIn('"answer": 42', runtime_module._coerce_to_text({"answer": 42}))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._tool_spec(descriptor)["function"]["name"],
            "cap.lookup",
        )
        merged_tools = runtime_module._merge_vendor_tools(  # pylint: disable=protected-access
            vendor_params={"seed": "base"},
            capabilities=(descriptor,),
        )
        self.assertEqual(merged_tools["tool_choice"], "auto")
        self.assertEqual(
            runtime_module._merge_vendor_tools(  # pylint: disable=protected-access
                vendor_params={"seed": "base"},
                capabilities=(),
            )["seed"],
            "base",
        )
        self.assertEqual(len(tool_invocations), 2)
        self.assertEqual(tool_invocations[0].arguments, {"query": "abc"})
        self.assertEqual(tool_invocations[1].arguments, {})
        dict_invocation = runtime_module._tool_call_invocations(  # pylint: disable=protected-access
            [{"id": "call-4", "name": "cap.dict", "arguments": {"count": 1}}]
        )
        self.assertEqual(dict_invocation[0].arguments, {"count": 1})
        self.assertNotIn(
            "capability_result",
            LLMPlannerStrategy._observation_payload(  # pylint: disable=protected-access
                PlanObservation(kind="note", payload={"x": 1})
            ),
        )
        self.assertIsNone(runtime_module._cfg_section(None, "agent_runtime"))  # pylint: disable=protected-access
        self.assertIsNone(  # pylint: disable=protected-access
            runtime_module._cfg_section({"agent_runtime": ""}, "agent_runtime")
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._cfg_section({"agent_runtime": {"enabled": True}}, "agent_runtime"),
            {"enabled": True},
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._cfg_value({"enabled": True}, "enabled"),
            True,
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._cfg_value(SimpleNamespace(enabled=True), "enabled"),
            True,
        )
        self.assertEqual(  # pylint: disable=protected-access
            runtime_module._cfg_list({"routes": [1, 2]}, "routes"),
            [1, 2],
        )
        self.assertEqual(runtime_module._cfg_list({"routes": "nope"}, "routes"), [])  # pylint: disable=protected-access
        for status in PlanOutcomeStatus:
            mapped = runtime_module._outcome_status_to_run_status(  # pylint: disable=protected-access
                PlanOutcome(status=status)
            )
            self.assertIsInstance(mapped, PlanRunStatus)

    async def test_relational_service_wrappers_construct_with_runtime_tables(self) -> None:
        run_service = AgentPlanRunService(table="agent_runtime_plan_run", rsg=Mock())
        step_service = AgentPlanStepService(table="agent_runtime_plan_step", rsg=Mock())

        self.assertEqual(run_service.table, "agent_runtime_plan_run")
        self.assertEqual(step_service.table, "agent_runtime_plan_step")

    async def test_policy_resolver_supports_missing_and_dict_backed_config(self) -> None:
        resolver = CodeConfiguredAgentPolicyResolver(config=SimpleNamespace())
        default_policy = await resolver.resolve_policy(_request())
        self.assertFalse(default_policy.enabled)

        dict_resolver = CodeConfiguredAgentPolicyResolver(
            config=SimpleNamespace(
                mugen={
                    "agent_runtime": {
                        "enabled": True,
                        "background_enabled": False,
                        "routes": [
                            {
                                "service_route_key": "support.primary",
                                "background_enabled": True,
                                "max_iterations": 7,
                            }
                        ],
                    }
                }
            )
        )

        route_policy = await dict_resolver.resolve_policy(_request())

        self.assertTrue(route_policy.enabled)
        self.assertTrue(route_policy.background_enabled)
        self.assertEqual(route_policy.max_iterations, 7)

        missing_agent_resolver = CodeConfiguredAgentPolicyResolver(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    agent_runtime=SimpleNamespace(
                        enabled=True,
                        routes=[SimpleNamespace(service_route_key=None, background_enabled=True)],
                    )
                )
            )
        )
        missing_agent_policy = await missing_agent_resolver.resolve_policy(
            _request(service_route_key=None)
        )
        self.assertTrue(missing_agent_policy.background_enabled)

        unresolved_agent_policy = await dict_resolver.resolve_policy(
            _request(service_route_key="support.primary", metadata={"x": 1})
        )
        self.assertNotIn("agent_definition_missing", unresolved_agent_policy.metadata)

        unknown_agent_policy = await CodeConfiguredAgentPolicyResolver(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    agent_runtime=SimpleNamespace(
                        enabled=True,
                        agent_key="coordinator.root",
                    )
                )
            )
        ).resolve_policy(_request(agent_key="missing.agent"))
        self.assertEqual(unknown_agent_policy.agent_key, "missing.agent")
        self.assertEqual(
            unknown_agent_policy.metadata["agent_definition_missing"],
            "missing.agent",
        )

    async def test_relational_plan_run_store_row_to_run_handles_rows_without_lineage(self) -> None:
        store = RelationalPlanRunStore(
            run_service=_FakeRunService(),
            step_service=_FakeStepService(),
        )
        now = datetime.now(timezone.utc)
        row = SimpleNamespace(
            id=uuid.uuid4(),
            mode=PlanRunMode.BACKGROUND.value,
            status=PlanRunStatus.PREPARED.value,
            policy_json=runtime_module._serialize_policy(  # pylint: disable=protected-access
                AgentRuntimePolicy(enabled=True, background_enabled=True)
            ),
            run_state_json=runtime_module._serialize_state(  # pylint: disable=protected-access
                PlanRunState(goal="hello")
            ),
            request_json={"mode": "background", "scope": runtime_module._scope_to_dict(_scope())},  # pylint: disable=protected-access
            service_route_key="support.primary",
            parent_run_id=None,
            root_run_id=None,
            agent_key=None,
            spawned_by_step_no=None,
            join_state_json=None,
            current_sequence_no=0,
            next_wakeup_at=None,
            lease_owner=None,
            lease_expires_at=None,
            final_outcome_json=None,
            created_at=now,
            updated_at=now,
            row_version=1,
            metadata_json={},
        )

        prepared = store._row_to_run(row)  # pylint: disable=protected-access

        self.assertIsNone(prepared.lineage)

    async def test_llm_planner_uses_prepared_context_with_tool_calls(self) -> None:
        capability = CapabilityDescriptor(
            key="cap.lookup",
            title="Lookup",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        request = _request(
            prepared_context=_prepared_context(),
            available_capabilities=(capability,),
        )
        run = _run(request=request)
        completion_gateway = Mock()
        completion_gateway.get_completion = AsyncMock(
            return_value=CompletionResponse(
                content="tool requested",
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {
                            "name": "cap.lookup",
                            "arguments": '{"query":"abc"}',
                        },
                    }
                ],
            )
        )
        planner = LLMPlannerStrategy(
            completion_gateway=completion_gateway,
            logging_gateway=Mock(),
        )

        decision = await planner.next_decision(
            request,
            run,
            (),
            policy=run.policy,
        )

        self.assertEqual(decision.kind, PlanDecisionKind.EXECUTE_ACTION)
        self.assertEqual(decision.capability_invocations[0].arguments, {"query": "abc"})
        sent_request = completion_gateway.get_completion.await_args.args[0]
        self.assertEqual(sent_request.model, "test-model")
        self.assertEqual(sent_request.vendor_params["tools"][0]["function"]["name"], "cap.lookup")
        self.assertFalse(sent_request.vendor_params["parallel_tool_calls"])

    async def test_llm_planner_appends_observations_and_builds_fallback_requests(self) -> None:
        capability = CapabilityDescriptor(key="cap.lookup", title="Lookup")
        observation = PlanObservation(
            kind="tool",
            summary="lookup",
            payload={"query": "abc"},
            success=False,
            capability_result=CapabilityResult(
                capability_key="cap.lookup",
                ok=False,
                error_message="bad_gateway",
                status_code=502,
                result={"detail": "failed"},
            ),
        )
        completion_gateway = Mock()
        completion_gateway.get_completion = AsyncMock(
            side_effect=[
                CompletionResponse(content={"answer": "after observation"}, tool_calls=[]),
                CompletionResponse(content={"answer": "without context"}, tool_calls=[]),
            ]
        )
        planner = LLMPlannerStrategy(
            completion_gateway=completion_gateway,
            logging_gateway=Mock(),
        )

        context_request = _request(
            prepared_context=_prepared_context(),
            available_capabilities=(capability,),
        )
        context_run = _run(request=context_request)
        context_decision = await planner.next_decision(
            context_request,
            context_run,
            (observation,),
            policy=context_run.policy,
        )

        fallback_request = _request(
            prepared_context=None,
            available_capabilities=(capability,),
        )
        fallback_run = _run(request=fallback_request)
        fallback_decision = await planner.next_decision(
            fallback_request,
            fallback_run,
            (observation,),
            policy=fallback_run.policy,
        )
        await planner.finalize_run(
            fallback_request,
            fallback_run,
            PlanOutcome(status=PlanOutcomeStatus.COMPLETED, assistant_response="done"),
            policy=fallback_run.policy,
        )

        self.assertEqual(context_decision.kind, PlanDecisionKind.RESPOND)
        self.assertIn('"after observation"', context_decision.response_text)
        self.assertIn('"without context"', fallback_decision.response_text)
        first_request = completion_gateway.get_completion.await_args_list[0].args[0]
        self.assertEqual(first_request.messages[-1].content["instruction"], "Continue using tools if needed, otherwise respond to the user.")
        self.assertEqual(
            first_request.messages[-1].content["agent_observations"][0]["capability_result"]["status_code"],
            502,
        )
        second_request = completion_gateway.get_completion.await_args_list[1].args[0]
        self.assertEqual(second_request.messages[0].role, "system")
        self.assertEqual(second_request.messages[1].content["goal"], "Handle the request")

    async def test_llm_evaluator_covers_pass_retry_escalate_and_prompt_parsing(self) -> None:
        request = _request()
        run = _run(request=request)
        failure_observation = PlanObservation(
            kind="tool",
            payload={"query": "abc"},
            capability_result=CapabilityResult(
                capability_key="cap.lookup",
                ok=False,
                error_message="lookup_failed",
                status_code=500,
            ),
        )

        evaluator = LLMEvaluationStrategy(
            completion_gateway=SimpleNamespace(
                get_completion=AsyncMock(
                    side_effect=RuntimeError("provider down"),
                )
            ),
            logging_gateway=Mock(),
        )
        fallback_step = await evaluator.evaluate_step(
            EvaluationRequest(request=request, run=run, observations=(failure_observation,)),
            policy=run.policy,
        )
        pass_step = await evaluator.evaluate_step(
            EvaluationRequest(request=request, run=run, observations=()),
            policy=run.policy,
        )
        blank_response = await evaluator.evaluate_response(
            EvaluationRequest(request=request, run=run, draft_response_text=" "),
            policy=run.policy,
        )
        failed_run = await evaluator.evaluate_run(
            EvaluationRequest(request=request, run=run),
            PlanOutcome(status=PlanOutcomeStatus.FAILED, error_message="broken"),
            policy=run.policy,
        )

        self.assertEqual(fallback_step.status, EvaluationStatus.REPLAN)
        self.assertEqual(pass_step.status, EvaluationStatus.PASS)
        self.assertEqual(blank_response.status, EvaluationStatus.RETRY)
        self.assertEqual(failed_run.status, EvaluationStatus.ESCALATE)

        completion_gateway = SimpleNamespace(
            get_completion=AsyncMock(
                side_effect=[
                    CompletionResponse(content='{"status":"invalid"}'),
                    CompletionResponse(
                        content='{"status":"retry","reasons":[" try_again ",""],"recommended_decision":"respond"}'
                    ),
                    CompletionResponse(content="not-json"),
                    CompletionResponse(content='{"status":"pass","reasons":["ok"]}'),
                ]
            )
        )
        logging_gateway = Mock()
        prompted_evaluator = LLMEvaluationStrategy(
            completion_gateway=completion_gateway,
            logging_gateway=logging_gateway,
        )

        self.assertIsNone(
            await prompted_evaluator._prompt_evaluator({"stage": "invalid"})  # pylint: disable=protected-access
        )
        prompted_result = await prompted_evaluator._prompt_evaluator(  # pylint: disable=protected-access
            {"stage": "valid"}
        )
        response_result = await prompted_evaluator.evaluate_response(
            EvaluationRequest(request=request, run=run, draft_response_text="answer"),
            policy=run.policy,
        )
        run_result = await prompted_evaluator.evaluate_run(
            EvaluationRequest(request=request, run=run),
            PlanOutcome(status=PlanOutcomeStatus.COMPLETED, assistant_response="done"),
            policy=run.policy,
        )

        self.assertEqual(prompted_result.status, EvaluationStatus.RETRY)
        self.assertEqual(prompted_result.recommended_decision, PlanDecisionKind.RESPOND)
        self.assertEqual(response_result.status, EvaluationStatus.PASS)
        self.assertEqual(run_result.status, EvaluationStatus.PASS)
        logging_gateway.warning.assert_not_called()
        fallback_run_result = await LLMEvaluationStrategy(
            completion_gateway=SimpleNamespace(
                get_completion=AsyncMock(return_value=CompletionResponse(content="not-json"))
            ),
            logging_gateway=Mock(),
        ).evaluate_run(
            EvaluationRequest(request=request, run=run),
            PlanOutcome(status=PlanOutcomeStatus.COMPLETED, assistant_response="done"),
            policy=run.policy,
        )
        self.assertEqual(fallback_run_result.status, EvaluationStatus.PASS)

        prompted_gateway = SimpleNamespace(
            get_completion=AsyncMock(
                side_effect=[
                    CompletionResponse(content='{"status":"pass","reasons":"ignored"}'),
                    CompletionResponse(content='{"status":"retry","reasons":["retry"]}'),
                    CompletionResponse(content='{"status":"fail","reasons":["bad"]}'),
                ]
            )
        )
        prompted_public = LLMEvaluationStrategy(
            completion_gateway=prompted_gateway,
            logging_gateway=Mock(),
        )
        prompted_step = await prompted_public.evaluate_step(
            EvaluationRequest(request=request, run=run, observations=(failure_observation,)),
            policy=run.policy,
        )
        prompted_response = await prompted_public.evaluate_response(
            EvaluationRequest(request=request, run=run, draft_response_text="answer"),
            policy=run.policy,
        )
        prompted_run = await prompted_public.evaluate_run(
            EvaluationRequest(request=request, run=run),
            PlanOutcome(status=PlanOutcomeStatus.COMPLETED, assistant_response="done"),
            policy=run.policy,
        )

        self.assertEqual(prompted_step.status, EvaluationStatus.PASS)
        self.assertEqual(prompted_response.status, EvaluationStatus.RETRY)
        self.assertEqual(prompted_run.status, EvaluationStatus.FAIL)

    async def test_acp_capability_provider_lists_descriptors_and_supports_prefix(self) -> None:
        provider = ACPActionCapabilityProvider(admin_registry=None, logging_gateway=Mock())
        request = _request()
        run = _run(request=request)

        self.assertEqual(
            await provider.list_capabilities(request, run, policy=run.policy),
            [],
        )
        self.assertTrue(provider.supports("acp__ticket__update"))
        self.assertFalse(provider.supports("cap.lookup"))

        service = _ACPService()
        resource = SimpleNamespace(
            entity_set="ticket",
            service_key="ticket_service",
            capabilities=SimpleNamespace(
                actions={
                    "update": {"schema": _ActionSchema},
                    "status": {"schema": _ActionSchema},
                    "skip": {"schema": None},
                    "missing": {"schema": _ActionSchema},
                    "non_mapping": "ignored",
                }
            ),
        )
        registry = _AdminRegistry(
            resources={"ticket": resource},
            services={"ticket_service": service},
        )
        provider = ACPActionCapabilityProvider(
            admin_registry=registry,
            logging_gateway=Mock(),
        )

        descriptors = await provider.list_capabilities(request, run, policy=run.policy)
        fallback_descriptor = provider._descriptor_from_action(  # pylint: disable=protected-access
            resource=resource,
            service=service,
            action_name="status",
            schema=_FallbackSchema,
        )
        pre_required_descriptor = provider._descriptor_from_action(  # pylint: disable=protected-access
            resource=resource,
            service=service,
            action_name="update",
            schema=_SchemaWithEntityRequired,
        )
        missing_descriptor = provider._descriptor_from_action(  # pylint: disable=protected-access
            resource=resource,
            service=SimpleNamespace(),
            action_name="missing",
            schema=_ActionSchema,
        )

        self.assertEqual([item.key for item in descriptors], ["acp__ticket__update", "acp__ticket__status"])
        self.assertIn("entity_id", descriptors[0].input_schema["required"])
        self.assertEqual(fallback_descriptor.input_schema["type"], "object")
        self.assertEqual(
            pre_required_descriptor.input_schema["required"].count("entity_id"),
            1,
        )
        self.assertIsNone(missing_descriptor)

    async def test_acp_capability_provider_execute_covers_success_and_failures(self) -> None:
        logging_gateway = Mock()
        provider = ACPActionCapabilityProvider(admin_registry=None, logging_gateway=logging_gateway)
        request = _request(metadata={"auth_user_id": "33333333-3333-3333-3333-333333333333"})
        run = _run(request=request)

        unavailable = await provider.execute(
            request,
            run,
            CapabilityInvocation(capability_key="acp__ticket__update"),
            CapabilityDescriptor(key="acp__ticket__update", title="Update"),
            policy=run.policy,
        )
        self.assertEqual(unavailable.error_message, "admin_registry_unavailable")

        service = _ACPService()
        resource = SimpleNamespace(
            entity_set="ticket",
            service_key="ticket_service",
            capabilities=SimpleNamespace(actions={"update": {"schema": _ActionSchema}}),
        )
        registry = _AdminRegistry(
            resources={"ticket": resource},
            services={"ticket_service": service},
        )
        provider = ACPActionCapabilityProvider(
            admin_registry=registry,
            logging_gateway=logging_gateway,
        )

        invalid_metadata = await provider.execute(
            request,
            run,
            CapabilityInvocation(capability_key="acp__ticket__update"),
            CapabilityDescriptor(
                key="acp__ticket__update",
                title="Update",
                metadata={"entity_set": "ticket"},
            ),
            policy=run.policy,
        )
        missing_handler = await provider.execute(
            request,
            run,
            CapabilityInvocation(capability_key="acp__ticket__missing"),
            CapabilityDescriptor(
                key="acp__ticket__missing",
                title="Missing",
                metadata={
                    "entity_set": "ticket",
                    "action_name": "missing",
                    "schema": _ActionSchema,
                },
            ),
            policy=run.policy,
        )
        validation_failed = await provider.execute(
            request,
            run,
            CapabilityInvocation(capability_key="acp__ticket__update", arguments={"note": "x"}),
            CapabilityDescriptor(
                key="acp__ticket__update",
                title="Update",
                metadata={
                    "entity_set": "ticket",
                    "action_name": "update",
                    "schema": _FailingSchema,
                },
            ),
            policy=run.policy,
        )
        entity_required = await provider.execute(
            request,
            run,
            CapabilityInvocation(capability_key="acp__ticket__update", arguments={"note": "x"}),
            CapabilityDescriptor(
                key="acp__ticket__update",
                title="Update",
                metadata={
                    "entity_set": "ticket",
                    "action_name": "update",
                    "schema": _ActionSchema,
                },
            ),
            policy=run.policy,
        )

        auth_only_descriptor = CapabilityDescriptor(
            key="acp__ticket__auth_only",
            title="Auth Only",
            metadata={
                "entity_set": "ticket",
                "action_name": "auth_only",
                "schema": _ActionSchema,
            },
        )
        no_auth_request = _request(sender_id=None, metadata={})
        auth_required = await provider.execute(
            no_auth_request,
            _run(request=no_auth_request),
            CapabilityInvocation(capability_key="acp__ticket__auth_only", arguments={"note": "x"}),
            auth_only_descriptor,
            policy=run.policy,
        )

        raise_descriptor = CapabilityDescriptor(
            key="acp__ticket__raise",
            title="Raise",
            metadata={
                "entity_set": "ticket",
                "action_name": "raise",
                "schema": _ActionSchema,
            },
        )
        raised = await provider.execute(
            request,
            run,
            CapabilityInvocation(capability_key="acp__ticket__raise", arguments={"note": "x"}),
            raise_descriptor,
            policy=run.policy,
        )

        status_descriptor = CapabilityDescriptor(
            key="acp__ticket__status",
            title="Status",
            metadata={
                "entity_set": "ticket",
                "action_name": "status",
                "schema": _ActionSchema,
            },
        )
        status_result = await provider.execute(
            request,
            run,
            CapabilityInvocation(capability_key="acp__ticket__status", arguments={"note": "x"}),
            status_descriptor,
            policy=run.policy,
        )

        update_descriptor = CapabilityDescriptor(
            key="acp__ticket__update",
            title="Update",
            metadata={
                "entity_set": "ticket",
                "action_name": "update",
                "schema": _ActionSchema,
            },
        )
        successful = await provider.execute(
            request,
            run,
            CapabilityInvocation(
                capability_key="acp__ticket__update",
                arguments={
                    "entity_id": "44444444-4444-4444-4444-444444444444",
                    "note": "x",
                },
            ),
            update_descriptor,
            policy=run.policy,
        )
        plain_descriptor = CapabilityDescriptor(
            key="acp__ticket__plain",
            title="Plain",
            metadata={
                "entity_set": "ticket",
                "action_name": "plain",
                "schema": _ActionSchema,
            },
        )
        plain_result = await provider.execute(
            request,
            run,
            CapabilityInvocation(capability_key="acp__ticket__plain"),
            plain_descriptor,
            policy=run.policy,
        )

        self.assertEqual(invalid_metadata.error_message, "invalid_capability_metadata")
        self.assertEqual(missing_handler.error_message, "capability_handler_missing")
        self.assertIn("validation_failed", validation_failed.error_message)
        self.assertEqual(entity_required.error_message, "entity_id_required")
        self.assertEqual(auth_required.error_message, "auth_user_id_required")
        self.assertEqual(raised.error_message, "boom")
        self.assertFalse(status_result.ok)
        self.assertTrue(successful.ok)
        self.assertEqual(successful.status_code, 202)
        self.assertTrue(plain_result.ok)
        self.assertIsNone(plain_result.status_code)
        update_call = next(call for call in service.calls if "entity_id" in call)
        self.assertEqual(update_call["data"]["validated"], True)
        self.assertEqual(
            str(update_call["where"]["tenant_id"]),
            request.scope.tenant_id,
        )
        logging_gateway.warning.assert_called_once()

    async def test_allowlist_guard_and_response_synthesizer_cover_all_paths(self) -> None:
        request = _request()
        run = _run(request=request)
        descriptor = CapabilityDescriptor(key="cap.lookup", title="Lookup")
        guard = AllowlistExecutionGuard()

        await guard.validate(
            request,
            run,
            CapabilityInvocation(capability_key="cap.lookup"),
            descriptor,
            policy=AgentRuntimePolicy(enabled=True),
        )
        with self.assertRaisesRegex(RuntimeError, "not allowed"):
            await guard.validate(
                request,
                run,
                CapabilityInvocation(capability_key="cap.other"),
                descriptor,
                policy=AgentRuntimePolicy(
                    enabled=True,
                    capability_allow=("cap.lookup",),
                ),
            )

        synthesizer = TextResponseSynthesizer()
        payloads = await synthesizer.synthesize(
            request,
            run,
            PlanDecision(
                kind=PlanDecisionKind.RESPOND,
                response_payloads=({"type": "text", "content": "payload"},),
            ),
            policy=run.policy,
        )
        completion_payload = await synthesizer.synthesize(
            request,
            run,
            PlanDecision(
                kind=PlanDecisionKind.RESPOND,
                completion=CompletionResponse(content={"answer": 42}),
            ),
            policy=run.policy,
        )
        blank_payload = await synthesizer.synthesize(
            request,
            run,
            PlanDecision(kind=PlanDecisionKind.RESPOND, response_text=" "),
            policy=run.policy,
        )

        self.assertEqual(payloads, [{"type": "text", "content": "payload"}])
        self.assertIn('"answer": 42', completion_payload[0]["content"])
        self.assertEqual(blank_payload, [])

    async def test_relational_plan_run_store_edges_cover_missing_rows_leases_and_filters(
        self,
    ) -> None:
        run_service = _FakeRunService()
        step_service = _FakeStepService()
        store = RelationalPlanRunStore(run_service=run_service, step_service=step_service)
        missing_run_id = "99999999-9999-9999-9999-999999999999"

        self.assertIsNone(await store.load_run(" "))
        self.assertIsNone(
            await store.acquire_lease(
                run_id=missing_run_id,
                owner="worker-1",
                lease_seconds=30,
            )
        )
        await store.release_lease(run_id=missing_run_id, owner="worker-1")
        with self.assertRaisesRegex(RuntimeError, "Unknown plan run"):
            await store.list_steps(run_id=missing_run_id)

        base_policy = AgentRuntimePolicy(enabled=True, background_enabled=True)
        due = await store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="due"),
            policy=base_policy,
        )
        active_lease = await store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="leased"),
            policy=base_policy,
        )
        future_wake = await store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="wake"),
            policy=base_policy,
        )
        stopped = await store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="stopped", status=PlanRunStatus.STOPPED),
            policy=base_policy,
        )
        second_due = await store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="second due"),
            policy=base_policy,
        )

        active_row = run_service.rows[uuid.UUID(active_lease.run_id)]
        active_row.lease_owner = "worker-1"
        active_row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        wake_row = run_service.rows[uuid.UUID(future_wake.run_id)]
        wake_row.next_wakeup_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        stopped_row = run_service.rows[uuid.UUID(stopped.run_id)]
        stopped_row.status = PlanRunStatus.STOPPED.value

        self.assertIsNone(
            await store.acquire_lease(
                run_id=active_lease.run_id,
                owner="worker-2",
                lease_seconds=30,
            )
        )
        renewed = await store.acquire_lease(
            run_id=active_lease.run_id,
            owner="worker-1",
            lease_seconds=30,
        )
        self.assertEqual(renewed.owner, "worker-1")

        await store.release_lease(run_id=active_lease.run_id, owner="worker-2")
        self.assertEqual(run_service.rows[uuid.UUID(active_lease.run_id)].lease_owner, "worker-1")
        await store.release_lease(run_id=active_lease.run_id, owner="worker-1")
        self.assertIsNone(run_service.rows[uuid.UUID(active_lease.run_id)].lease_owner)

        due_runs = await store.list_runnable_runs(limit=1)
        all_due_runs = await store.list_runnable_runs(limit=10)
        self.assertEqual(len(due_runs), 1)
        self.assertIn(due_runs[0].run_id, {due.run_id, second_due.run_id})
        self.assertEqual(
            {item.run_id for item in all_due_runs},
            {due.run_id, active_lease.run_id, second_due.run_id},
        )

        due.state.summary = "saved"
        due.lease = PlanLease(
            owner="worker-3",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        due.final_outcome = PlanOutcome(
            status=PlanOutcomeStatus.WAITING,
            assistant_response="waiting",
        )
        saved = await store.save_run(due)
        cursor = await store.append_step(
            run_id=saved.run_id,
            step=PlanRunStep(
                run_id=saved.run_id,
                sequence_no=saved.cursor.next_sequence_no,
                step_kind=PlanRunStepKind.EFFECT,
                payload={"status": "saved"},
                occurred_at=datetime.now(timezone.utc),
            ),
        )
        loaded = await store.load_run(saved.run_id)
        steps = await store.list_steps(run_id=saved.run_id, limit=1)

        self.assertEqual(loaded.final_outcome.status, PlanOutcomeStatus.WAITING)
        self.assertEqual(loaded.lease.owner, "worker-3")
        self.assertEqual(cursor.next_sequence_no, 2)
        self.assertEqual(steps[0].step_kind, PlanRunStepKind.EFFECT)

    async def test_relational_plan_run_store_raises_explicit_stale_row_version_errors(
        self,
    ) -> None:
        run_service = _FakeRunService()
        step_service = _FakeStepService()
        store = RelationalPlanRunStore(run_service=run_service, step_service=step_service)
        base_policy = AgentRuntimePolicy(enabled=True, background_enabled=True)

        saved_run = await store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="saved"),
            policy=base_policy,
        )
        run_service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "stale row_version"):
            await store.save_run(saved_run)

        append_run_service = _FakeRunService()
        append_step_service = _FakeStepService()
        append_store = RelationalPlanRunStore(
            run_service=append_run_service,
            step_service=append_step_service,
        )
        append_run = await append_store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="append"),
            policy=base_policy,
        )
        append_run_service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "stale row_version"):
            await append_store.append_step(
                run_id=append_run.run_id,
                step=PlanRunStep(
                    run_id=append_run.run_id,
                    sequence_no=append_run.cursor.next_sequence_no,
                    step_kind=PlanRunStepKind.EFFECT,
                    payload={"step": "append"},
                    occurred_at=datetime.now(timezone.utc),
                ),
            )

        lease_run_service = _FakeRunService()
        lease_store = RelationalPlanRunStore(
            run_service=lease_run_service,
            step_service=_FakeStepService(),
        )
        lease_run = await lease_store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="lease"),
            policy=base_policy,
        )
        lease_run_service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "stale row_version"):
            await lease_store.acquire_lease(
                run_id=lease_run.run_id,
                owner="worker-1",
                lease_seconds=30,
            )

        finalize_run_service = _FakeRunService()
        finalize_store = RelationalPlanRunStore(
            run_service=finalize_run_service,
            step_service=_FakeStepService(),
        )
        finalize_run = await finalize_store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="finalize"),
            policy=base_policy,
        )
        finalize_run_service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "stale row_version"):
            await finalize_store.finalize_run(
                run_id=finalize_run.run_id,
                outcome=PlanOutcome(status=PlanOutcomeStatus.COMPLETED),
            )

        release_run_service = _FakeRunService()
        release_store = RelationalPlanRunStore(
            run_service=release_run_service,
            step_service=_FakeStepService(),
        )
        release_run = await release_store.create_run(
            _request(mode=PlanRunMode.BACKGROUND),
            state=PlanRunState(goal="release"),
            policy=base_policy,
        )
        release_row = release_run_service.rows[uuid.UUID(release_run.run_id)]
        release_row.lease_owner = "worker-1"
        release_row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        release_run_service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "stale row_version"):
            await release_store.release_lease(
                run_id=release_run.run_id,
                owner="worker-1",
            )


if __name__ == "__main__":
    unittest.main()
