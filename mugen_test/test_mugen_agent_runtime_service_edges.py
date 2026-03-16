"""Edge and coverage tests for mugen.core.service.agent_runtime."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.agent import (
    AgentRuntimePolicy,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityResult,
    DelegationArtifactRef,
    DelegationInstruction,
    EvaluationRequest,
    EvaluationResult,
    EvaluationStatus,
    JoinPolicy,
    JoinState,
    PlanDecision,
    PlanDecisionKind,
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
import mugen.core.service.agent_runtime as svc_module
from mugen.core.service.agent_runtime import (
    DefaultAgentExecutor,
    DefaultAgentRuntime,
    DefaultEvaluationEngine,
    DefaultPlanRunStore,
    DefaultPlanningEngine,
)


def _scope() -> ContextScope:
    return ContextScope(
        tenant_id="11111111-1111-1111-1111-111111111111",
        platform="matrix",
        channel_id="matrix",
        room_id="room-1",
        sender_id="22222222-2222-2222-2222-222222222222",
        conversation_id="room-1",
    )


def _prepared_context() -> PreparedContextTurn:
    return PreparedContextTurn(
        completion_request=CompletionRequest(
            messages=[CompletionMessage(role="user", content="hello")]
        ),
        bundle=ContextBundle(
            policy=ContextPolicy(),
            state=ContextState(revision=1),
            selected_candidates=(),
            dropped_candidates=(),
        ),
        state_handle="state-1",
        commit_token="commit-1",
    )


def _request(
    *,
    mode: PlanRunMode = PlanRunMode.CURRENT_TURN,
    prepared_context: PreparedContextTurn | None = None,
    run_id: str | None = None,
    service_route_key: str | None = "support.primary",
    agent_key: str | None = None,
    metadata: dict | None = None,
) -> PlanRunRequest:
    return PlanRunRequest(
        mode=mode,
        scope=_scope(),
        user_message="Handle the request",
        service_route_key=service_route_key,
        agent_key=agent_key,
        prepared_context=prepared_context,
        run_id=run_id,
        metadata=dict(metadata or {}),
    )


def _run(
    *,
    run_id: str = "run-1",
    mode: PlanRunMode = PlanRunMode.CURRENT_TURN,
    status: PlanRunStatus = PlanRunStatus.PREPARED,
    policy: AgentRuntimePolicy | None = None,
    request: PlanRunRequest | None = None,
) -> PreparedPlanRun:
    resolved_request = request or _request(mode=mode)
    return PreparedPlanRun(
        run_id=run_id,
        mode=mode,
        status=status,
        state=PlanRunState(goal=resolved_request.user_message, status=status),
        policy=policy
        or AgentRuntimePolicy(
            enabled=True,
            current_turn_enabled=True,
            background_enabled=True,
            max_iterations=4,
            max_background_iterations=4,
        ),
        request_snapshot={
            "mode": mode.value,
            "scope": asdict(resolved_request.scope),
            "user_message": resolved_request.user_message,
            "message_id": resolved_request.message_id,
            "trace_id": resolved_request.trace_id,
            "service_route_key": resolved_request.service_route_key,
            "agent_key": resolved_request.agent_key,
            "ingress_metadata": dict(resolved_request.ingress_metadata),
            "metadata": dict(resolved_request.metadata),
        },
        cursor=PlanRunCursor(run_id=run_id),
        service_route_key=resolved_request.service_route_key,
        row_version=1,
    )


def _registry(**overrides):
    base = dict(
        planners=[],
        evaluators=[],
        capability_providers=[],
        execution_guards=[],
        response_synthesizers=[],
        trace_sinks=[],
        policy_resolver=None,
        run_store=None,
        scheduler=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_registry(registry):
    return patch.object(
        svc_module.di,
        "container",
        new=SimpleNamespace(
            get_ext_service=lambda _name, default=None: registry,
        ),
    )


def _append_cursor_side_effect():
    async def _append_step(*, run_id: str, step) -> PlanRunCursor:
        return PlanRunCursor(
            run_id=run_id,
            next_sequence_no=step.sequence_no + 1,
            status=PlanRunStatus.ACTIVE,
        )

    return _append_step


class _DummyService(svc_module._AgentServiceBase):
    pass


class TestMugenAgentRuntimeServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Close coverage over helper and edge behavior in the core service layer."""

    async def asyncSetUp(self) -> None:
        self._container_patch = _patch_registry(_registry())
        self._container_patch.start()

    async def asyncTearDown(self) -> None:
        self._container_patch.stop()

    async def test_helper_serializers_and_snapshot_helpers(self) -> None:
        completion = CompletionResponse(
            content="hello",
            model="gpt-test",
            stop_reason="done",
            message={"role": "assistant"},
            tool_calls=[{"id": "tool-1"}],
            usage=CompletionUsage(
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                vendor_fields={"cost": 0.1},
            ),
            vendor_fields={"trace": "1"},
        )
        capability_result = CapabilityResult(
            capability_key="cap.lookup",
            ok=True,
            result={"value": 1},
            status_code=200,
            metadata={"m": "v"},
        )
        observation = PlanObservation(
            kind="tool",
            summary="lookup",
            payload={"x": 1},
            success=True,
            capability_result=capability_result,
            completion=completion,
            metadata={"k": "v"},
        )
        decision = PlanDecision(
            kind=PlanDecisionKind.RESPOND,
            response_text="hello",
            response_payloads=({"type": "text", "content": "hello"},),
            capability_invocations=(
                CapabilityInvocation(
                    capability_key="cap.lookup",
                    arguments={"x": 1},
                    idempotency_key="idem-1",
                    metadata={"m": "v"},
                ),
            ),
            wait_until=datetime.now(timezone.utc),
            handoff_reason="needs_human",
            background_payload={"priority": "high"},
            completion=completion,
            rationale_summary="done",
            metadata={"trace": "1"},
        )
        evaluation = EvaluationResult(
            status=EvaluationStatus.REPLAN,
            reasons=("try_again",),
            scores={"quality": 0.9},
            recommended_decision=PlanDecisionKind.RESPOND,
            metadata={"trace": "1"},
        )
        outcome = PlanOutcome(
            status=PlanOutcomeStatus.SPAWNED_BACKGROUND,
            final_user_responses=({"type": "text", "content": "queued"},),
            assistant_response="queued",
            completion=completion,
            background_run_id="run-bg",
            error_message="none",
            metadata={"trace": "1"},
        )

        self.assertIsNone(svc_module._serialize_capability_result(None))  # pylint: disable=protected-access
        serialized_completion = svc_module._serialize_completion(completion)  # pylint: disable=protected-access
        serialized_completion_no_usage = svc_module._serialize_completion(  # pylint: disable=protected-access
            CompletionResponse(content="hello")
        )
        serialized_observation = svc_module._serialize_observation(observation)  # pylint: disable=protected-access
        serialized_decision = svc_module._serialize_decision(decision)  # pylint: disable=protected-access
        serialized_evaluation = svc_module._serialize_evaluation(evaluation)  # pylint: disable=protected-access
        serialized_outcome = svc_module._serialize_outcome(outcome)  # pylint: disable=protected-access
        derived_request = svc_module._request_from_snapshot(  # pylint: disable=protected-access
            {
                "mode": "background",
                "scope": asdict(_scope()),
                "user_message": "snapshot",
                "message_id": "msg-1",
                "trace_id": "trace-1",
                "service_route_key": "support.primary",
                "agent_key": "coordinator.root",
                "ingress_metadata": {"trace": "1"},
                "metadata": {"origin": "resume"},
            },
            run_id="run-1",
        )
        lineage = PlanRunLineage(
            parent_run_id="run-parent",
            root_run_id="run-root",
            spawned_by_step_no=3,
            agent_key="specialist.lookup",
        )
        artifact = DelegationArtifactRef(
            artifact_key="artifact.summary",
            source_run_id="run-parent",
            source_step_sequence_no=2,
            summary="facts",
            payload={"value": 42},
            metadata={"trace": "1"},
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
            last_joined_sequence_no=3,
            timeout_at=datetime.now(timezone.utc),
            policy=join_policy,
            metadata={"trace": "1"},
        )

        self.assertEqual(serialized_completion["usage"]["total_tokens"], 3)
        self.assertIsNone(serialized_completion_no_usage["usage"])
        self.assertEqual(serialized_observation["capability_result"]["status_code"], 200)
        self.assertEqual(
            serialized_decision["capability_invocations"][0]["idempotency_key"],
            "idem-1",
        )
        self.assertEqual(
            serialized_evaluation["recommended_decision"],
            PlanDecisionKind.RESPOND.value,
        )
        self.assertEqual(serialized_outcome["background_run_id"], "run-bg")
        self.assertEqual(
            svc_module._first_text_response(  # pylint: disable=protected-access
                [
                    {"type": "image", "content": {"id": "1"}},
                    {"type": "text", "content": "hello"},
                ]
            ),
            "hello",
        )
        self.assertEqual(
            svc_module._first_text_response(  # pylint: disable=protected-access
                [{"type": "text", "content": {"not": "string"}}]
            ),
            "",
        )
        for status in PlanOutcomeStatus:
            mapped = svc_module._status_from_outcome(  # pylint: disable=protected-access
                PlanOutcome(status=status)
            )
            self.assertIsInstance(mapped, PlanRunStatus)
        self.assertEqual(derived_request.agent_key, "coordinator.root")
        self.assertEqual(derived_request.mode, PlanRunMode.BACKGROUND)
        self.assertEqual(derived_request.metadata["origin"], "resume")
        self.assertIsNone(svc_module._serialize_lineage(None))  # pylint: disable=protected-access
        self.assertIsNone(svc_module._deserialize_lineage(None))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._deserialize_lineage(
                svc_module._serialize_lineage(lineage)  # pylint: disable=protected-access
            ).agent_key,
            "specialist.lookup",
        )
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._serialize_artifact_ref(artifact)["metadata"]["trace"],
            "1",
        )
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._deserialize_artifact_ref(
                {
                    "artifact_key": "artifact.summary",
                    "source_run_id": "run-parent",
                    "payload": {"value": 42},
                }
            ).artifact_key,
            "artifact.summary",
        )
        self.assertIsNone(svc_module._serialize_join_policy(None))  # pylint: disable=protected-access
        self.assertIsNone(svc_module._deserialize_join_policy(None))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._deserialize_join_policy(
                svc_module._serialize_join_policy(join_policy)  # pylint: disable=protected-access
            ).on_required_child_failed,
            PlanOutcomeStatus.FAILED,
        )
        self.assertIsNone(svc_module._serialize_join_state(None))  # pylint: disable=protected-access
        self.assertIsNone(svc_module._deserialize_join_state(None))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._deserialize_join_state(
                svc_module._serialize_join_state(join_state)  # pylint: disable=protected-access
            ).last_joined_sequence_no,
            3,
        )
        self.assertIsNone(  # pylint: disable=protected-access
            svc_module._deserialize_join_state({"timeout_at": ""}).timeout_at
        )
        self.assertIs(  # pylint: disable=protected-access
            svc_module._lineage_from_request_metadata({"agent_lineage": lineage}),
            lineage,
        )
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._lineage_from_request_metadata(
                {"agent_lineage": svc_module._serialize_lineage(lineage)}  # pylint: disable=protected-access
            ).root_run_id,
            "run-root",
        )
        self.assertIs(  # pylint: disable=protected-access
            svc_module._join_state_from_request_metadata({"agent_join_state": join_state}),
            join_state,
        )
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._join_state_from_request_metadata(
                {"agent_join_state": svc_module._serialize_join_state(join_state)}  # pylint: disable=protected-access
            ).required_child_run_ids,
            ("child-1",),
        )
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._outcome_status_from_run_status(PlanRunStatus.PREPARED),
            PlanOutcomeStatus.FAILED,
        )
        self.assertEqual(  # pylint: disable=protected-access
            svc_module._outcome_status_from_run_status(PlanRunStatus.ACTIVE),
            PlanOutcomeStatus.FAILED,
        )

    async def test_agent_service_base_resolves_policy_and_run_store_edges(self) -> None:
        request = _request()

        with _patch_registry(_registry()):
            service = _DummyService(config=SimpleNamespace(), logging_gateway=Mock())
            policy = await service._resolve_policy(request)  # pylint: disable=protected-access
            self.assertFalse(policy.enabled)
            with self.assertRaisesRegex(RuntimeError, "run store is not registered"):
                service._require_run_store()  # pylint: disable=protected-access

        resolver = Mock()
        resolver.resolve_policy = AsyncMock(
            return_value=AgentRuntimePolicy(enabled=True)
        )
        run_store = object()
        with _patch_registry(_registry(policy_resolver=resolver, run_store=run_store)):
            service = _DummyService(config=SimpleNamespace(), logging_gateway=Mock())
            policy = await service._resolve_policy(request)  # pylint: disable=protected-access
            self.assertTrue(policy.enabled)
            self.assertIs(  # pylint: disable=protected-access
                service._require_run_store(),
                run_store,
            )

    async def test_default_planning_engine_edges_and_selection(self) -> None:
        logging_gateway = Mock()
        policy_resolver = Mock()
        policy_resolver.resolve_policy = AsyncMock(
            return_value=AgentRuntimePolicy(
                enabled=True,
                current_turn_enabled=True,
                planner_key="preferred",
            )
        )
        run_store = Mock()
        fallback_planner = Mock(name="fallback")
        fallback_planner.name = "fallback"
        fallback_planner.next_decision = AsyncMock()
        fallback_planner.finalize_run = AsyncMock()
        preferred_planner = Mock(name="preferred")
        preferred_planner.name = "preferred"
        preferred_planner.next_decision = AsyncMock(
            return_value=PlanDecision(kind=PlanDecisionKind.RESPOND, response_text="hi")
        )
        preferred_planner.finalize_run = AsyncMock(side_effect=RuntimeError("boom"))

        engine = DefaultPlanningEngine(
            config=SimpleNamespace(),
            logging_gateway=logging_gateway,
        )

        with _patch_registry(
            _registry(
                planners=[fallback_planner, preferred_planner],
                policy_resolver=policy_resolver,
                run_store=run_store,
            )
        ):
            with self.assertRaisesRegex(TypeError, "PlanRunRequest"):
                await engine.prepare_run("bad")

            missing_request = _request(run_id="run-missing")
            run_store.load_run = AsyncMock(return_value=None)
            with self.assertRaisesRegex(RuntimeError, "Unknown plan run"):
                await engine.prepare_run(missing_request)

            existing_run = _run(run_id="run-1", request=_request(run_id="run-1"))
            run_store.load_run = AsyncMock(return_value=existing_run)
            run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
            resumed = await engine.prepare_run(_request(run_id="run-1"))
            self.assertEqual(resumed.run_id, "run-1")

            created_run = _run(
                run_id="run-2",
                request=_request(prepared_context=_prepared_context()),
                status=PlanRunStatus.PREPARED,
            )
            run_store.create_run = AsyncMock(return_value=created_run)
            run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
            prepared = await engine.prepare_run(
                _request(prepared_context=_prepared_context())
            )
            self.assertEqual(prepared.status, PlanRunStatus.ACTIVE)

            decision = await engine.next_decision(_request(), existing_run, ())
            self.assertEqual(decision.kind, PlanDecisionKind.RESPOND)

            finalized = await engine.finalize_run(
                _request(),
                existing_run,
                PlanOutcome(status=PlanOutcomeStatus.FAILED, error_message="boom"),
            )
            self.assertEqual(finalized.status, PlanRunStatus.FAILED)
            logging_gateway.warning.assert_called()

        with _patch_registry(_registry(run_store=run_store)):
            with self.assertRaisesRegex(RuntimeError, "planner strategy is not registered"):
                engine._select_planner(AgentRuntimePolicy())  # pylint: disable=protected-access

        with _patch_registry(
            _registry(
                planners=[fallback_planner, preferred_planner],
                run_store=run_store,
            )
        ):
            selected = engine._select_planner(  # pylint: disable=protected-access
                AgentRuntimePolicy(planner_key="missing")
            )
            self.assertIs(selected, fallback_planner)
            selected_default = engine._select_planner(  # pylint: disable=protected-access
                AgentRuntimePolicy(planner_key="")
            )
            self.assertIs(selected_default, fallback_planner)

    async def test_default_planning_engine_applies_agent_defaults_and_missing_agent_guards(
        self,
    ) -> None:
        engine = DefaultPlanningEngine(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )
        run_store = Mock()
        run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)

        with _patch_registry(
            _registry(
                policy_resolver=Mock(
                    resolve_policy=AsyncMock(
                        return_value=AgentRuntimePolicy(
                            enabled=True,
                            current_turn_enabled=True,
                            agent_key="coordinator.root",
                            metadata={"service_route_key": "support.fallback"},
                        )
                    )
                ),
                run_store=run_store,
            )
        ):
            created_run = _run(
                run_id="run-created",
                request=_request(prepared_context=_prepared_context()),
                status=PlanRunStatus.PREPARED,
            )
            run_store.create_run = AsyncMock(return_value=created_run)
            request = _request(prepared_context=_prepared_context())
            request.service_route_key = None
            request.agent_key = None
            prepared = await engine.prepare_run(request)
            self.assertEqual(prepared.service_route_key, "support.fallback")
            self.assertEqual(prepared.request_snapshot["agent_key"], "coordinator.root")

        existing = _run(run_id="run-existing", request=_request(run_id="run-existing"))
        existing.lineage = PlanRunLineage(root_run_id="run-existing", agent_key="old.agent")
        existing.request_snapshot["agent_key"] = "old.agent"
        with _patch_registry(
            _registry(
                policy_resolver=Mock(
                    resolve_policy=AsyncMock(
                        return_value=AgentRuntimePolicy(
                            enabled=True,
                            current_turn_enabled=True,
                            agent_key="specialist.lookup",
                        )
                    )
                ),
                run_store=Mock(
                    load_run=AsyncMock(return_value=existing),
                    save_run=AsyncMock(side_effect=lambda prepared_run: prepared_run),
                ),
            )
        ):
            resumed = await engine.prepare_run(_request(run_id="run-existing"))
            self.assertEqual(resumed.lineage.agent_key, "specialist.lookup")

        with _patch_registry(
            _registry(
                policy_resolver=Mock(
                    resolve_policy=AsyncMock(
                        return_value=AgentRuntimePolicy(
                            enabled=True,
                            current_turn_enabled=True,
                            metadata={"agent_definition_missing": "missing.agent"},
                        )
                    )
                ),
                run_store=run_store,
            )
        ):
            with self.assertRaisesRegex(RuntimeError, "Unknown agent definition: missing.agent"):
                await engine.prepare_run(_request(prepared_context=_prepared_context()))

    async def test_default_evaluation_engine_fallbacks_and_selection(self) -> None:
        engine = DefaultEvaluationEngine(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )
        run = _run()
        request = EvaluationRequest(
            request=_request(),
            run=run,
            observations=(
                PlanObservation(
                    kind="tool",
                    capability_result=CapabilityResult(
                        capability_key="cap.one",
                        ok=False,
                        error_message="failed",
                    ),
                ),
            ),
        )

        with _patch_registry(_registry()):
            step_result = await engine.evaluate_step(request)
            response_result = await engine.evaluate_response(
                EvaluationRequest(
                    request=_request(),
                    run=run,
                    draft_response_text=" ",
                )
            )
            run_result = await engine.evaluate_run(
                EvaluationRequest(request=_request(), run=run),
                PlanOutcome(status=PlanOutcomeStatus.FAILED, error_message="failed"),
            )
            self.assertEqual(step_result.status, EvaluationStatus.REPLAN)
            self.assertEqual(response_result.status, EvaluationStatus.RETRY)
            self.assertEqual(run_result.status, EvaluationStatus.ESCALATE)

        preferred = Mock()
        preferred.name = "preferred"
        preferred.evaluate_step = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )
        preferred.evaluate_response = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )
        preferred.evaluate_run = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )
        with _patch_registry(_registry(evaluators=[preferred])):
            run.policy.evaluator_key = "preferred"
            result = await engine.evaluate_step(request)
            response_result = await engine.evaluate_response(
                EvaluationRequest(
                    request=_request(),
                    run=run,
                    draft_response_text="hello",
                )
            )
            run_result = await engine.evaluate_run(
                EvaluationRequest(request=_request(), run=run),
                PlanOutcome(status=PlanOutcomeStatus.COMPLETED),
            )
            self.assertEqual(result.status, EvaluationStatus.PASS)
            self.assertEqual(response_result.status, EvaluationStatus.PASS)
            self.assertEqual(run_result.status, EvaluationStatus.PASS)

        with _patch_registry(_registry()):
            pass_result = await engine.evaluate_step(
                EvaluationRequest(
                    request=_request(),
                    run=_run(),
                    observations=(PlanObservation(kind="tool"),),
                )
            )
            response_pass = await engine.evaluate_response(
                EvaluationRequest(
                    request=_request(),
                    run=_run(),
                    draft_response_text="nonblank",
                )
            )
            run_pass = await engine.evaluate_run(
                EvaluationRequest(request=_request(), run=_run()),
                PlanOutcome(status=PlanOutcomeStatus.COMPLETED),
            )
            self.assertEqual(pass_result.status, EvaluationStatus.PASS)
            self.assertEqual(response_pass.status, EvaluationStatus.PASS)
            self.assertEqual(run_pass.status, EvaluationStatus.PASS)

        fallback = Mock()
        fallback.name = "fallback"
        fallback.evaluate_step = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )
        with _patch_registry(_registry(evaluators=[fallback, preferred])):
            run.policy.evaluator_key = "missing"
            selected = engine._select_evaluator(run.policy)  # pylint: disable=protected-access
            self.assertIs(selected, fallback)
            selected_default = engine._select_evaluator(  # pylint: disable=protected-access
                AgentRuntimePolicy(evaluator_key="")
            )
            self.assertIs(selected_default, fallback)

    async def test_default_agent_executor_filters_capabilities_and_covers_error_paths(
        self,
    ) -> None:
        logging_gateway = Mock()
        executor = DefaultAgentExecutor(
            config=SimpleNamespace(),
            logging_gateway=logging_gateway,
        )
        allowed_run = _run(
            policy=AgentRuntimePolicy(
                enabled=True,
                capability_allow=("cap.one",),
            )
        )
        provider = Mock()
        provider.list_capabilities = AsyncMock(
            return_value=[
                CapabilityDescriptor(key="cap.one", title="One"),
                CapabilityDescriptor(key="cap.one", title="Duplicate"),
                CapabilityDescriptor(key="cap.two", title="Two"),
            ]
        )
        provider.supports = Mock(side_effect=lambda key: key == "cap.one")
        provider.execute = AsyncMock(side_effect=RuntimeError("boom"))
        guard = Mock()
        guard.validate = AsyncMock()

        with _patch_registry(
            _registry(
                capability_providers=[provider],
                execution_guards=[guard],
            )
        ):
            listed = await executor.list_capabilities(_request(), allowed_run)
            self.assertEqual([item.key for item in listed], ["cap.one"])

            unknown = await executor.execute_capability(
                _request(),
                allowed_run,
                CapabilityInvocation(capability_key="cap.unknown"),
            )
            errored = await executor.execute_capability(
                _request(),
                allowed_run,
                CapabilityInvocation(capability_key="cap.one"),
            )

            self.assertEqual(unknown.error_message, "unknown_capability")
            self.assertEqual(errored.error_message, "boom")
            guard.validate.assert_awaited_once()
            logging_gateway.warning.assert_called()

        provider.execute = AsyncMock(
            return_value=CapabilityResult(capability_key="cap.one", ok=True)
        )
        provider.supports = Mock(return_value=False)
        with _patch_registry(_registry(capability_providers=[provider])):
            unsupported = await executor.execute_capability(
                _request(),
                allowed_run,
                CapabilityInvocation(capability_key="cap.one"),
            )
            self.assertEqual(unsupported.error_message, "unsupported_capability")

    async def test_default_plan_run_store_delegates_all_methods(self) -> None:
        run = _run()
        child = _run(run_id="run-child")
        step = PlanRunStep(
            run_id=run.run_id,
            sequence_no=1,
            step_kind=PlanRunStepKind.DECISION,
        )
        cursor = PlanRunCursor(run_id=run.run_id, next_sequence_no=2)
        store = Mock()
        store.create_run = AsyncMock(return_value=run)
        store.load_run = AsyncMock(return_value=run)
        store.save_run = AsyncMock(return_value=run)
        store.append_step = AsyncMock(return_value=cursor)
        store.acquire_lease = AsyncMock(return_value=None)
        store.release_lease = AsyncMock()
        store.list_runnable_runs = AsyncMock(return_value=[run])
        store.finalize_run = AsyncMock(
            return_value=PlanOutcome(status=PlanOutcomeStatus.COMPLETED)
        )
        store.list_steps = AsyncMock(return_value=[step])
        store.list_child_runs = AsyncMock(return_value=[child])
        store.load_run_graph = AsyncMock(return_value=[run, child])
        wrapper = DefaultPlanRunStore(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )

        with _patch_registry(_registry(run_store=store)):
            self.assertIs(
                await wrapper.create_run(
                    _request(),
                    state=PlanRunState(goal="hello"),
                    policy=AgentRuntimePolicy(),
                ),
                run,
            )
            self.assertIs(await wrapper.load_run(run.run_id), run)
            self.assertIs(await wrapper.save_run(run), run)
            self.assertIs(await wrapper.append_step(run_id=run.run_id, step=step), cursor)
            self.assertIsNone(
                await wrapper.acquire_lease(
                    run_id=run.run_id,
                    owner="worker",
                    lease_seconds=1,
                )
            )
            await wrapper.release_lease(run_id=run.run_id, owner="worker")
            self.assertEqual(
                await wrapper.list_runnable_runs(limit=1),
                [run],
            )
            self.assertEqual(
                (
                    await wrapper.finalize_run(
                        run_id=run.run_id,
                        outcome=PlanOutcome(status=PlanOutcomeStatus.COMPLETED),
                    )
                ).status,
                PlanOutcomeStatus.COMPLETED,
            )
            self.assertEqual(await wrapper.list_steps(run_id=run.run_id), [step])
            self.assertEqual(
                await wrapper.list_child_runs(run.run_id, terminal_only=True),
                [child],
            )
            self.assertEqual(await wrapper.load_run_graph(run.run_id), [run, child])

    async def test_agent_runtime_enablement_and_dependency_guards(self) -> None:
        resolver = Mock()
        resolver.resolve_policy = AsyncMock(
            side_effect=[
                AgentRuntimePolicy(enabled=False),
                AgentRuntimePolicy(enabled=True, current_turn_enabled=True),
                AgentRuntimePolicy(enabled=True, background_enabled=True),
            ]
        )
        runtime = DefaultAgentRuntime(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )
        with _patch_registry(_registry(policy_resolver=resolver)):
            self.assertFalse(await runtime.is_enabled_for_request(_request()))
            self.assertTrue(
                await runtime.is_enabled_for_request(_request(mode=PlanRunMode.CURRENT_TURN))
            )
            self.assertTrue(
                await runtime.is_enabled_for_request(_request(mode=PlanRunMode.BACKGROUND))
            )

        with self.assertRaisesRegex(ValueError, "current_turn mode"):
            await runtime.run_current_turn(_request(mode=PlanRunMode.BACKGROUND))
        with self.assertRaisesRegex(ValueError, "prepared_context"):
            await runtime.run_current_turn(_request())
        with self.assertRaisesRegex(RuntimeError, "planning_engine_service"):
            await runtime.run_current_turn(_request(prepared_context=_prepared_context()))

        with self.assertRaisesRegex(RuntimeError, "evaluation_engine_service"):
            await DefaultAgentRuntime(
                config=SimpleNamespace(),
                logging_gateway=Mock(),
                planning_engine_service=Mock(),
            ).run_current_turn(_request(prepared_context=_prepared_context()))
        with self.assertRaisesRegex(RuntimeError, "agent_executor_service"):
            await DefaultAgentRuntime(
                config=SimpleNamespace(),
                logging_gateway=Mock(),
                planning_engine_service=Mock(),
                evaluation_engine_service=Mock(),
            ).run_current_turn(_request(prepared_context=_prepared_context()))
        with self.assertRaisesRegex(RuntimeError, "plan_run_store_service"):
            await DefaultAgentRuntime(
                config=SimpleNamespace(),
                logging_gateway=Mock(),
                planning_engine_service=Mock(),
                evaluation_engine_service=Mock(),
                agent_executor_service=Mock(),
            ).run_current_turn(_request(prepared_context=_prepared_context()))

        with self.assertRaisesRegex(RuntimeError, "planning_engine_service"):
            await runtime.run_background_batch(owner="worker")
        with self.assertRaisesRegex(RuntimeError, "evaluation_engine_service"):
            await DefaultAgentRuntime(
                config=SimpleNamespace(),
                logging_gateway=Mock(),
                planning_engine_service=Mock(),
            ).run_background_batch(owner="worker")
        with self.assertRaisesRegex(RuntimeError, "agent_executor_service"):
            await DefaultAgentRuntime(
                config=SimpleNamespace(),
                logging_gateway=Mock(),
                planning_engine_service=Mock(),
                evaluation_engine_service=Mock(),
            ).run_background_batch(owner="worker")
        with self.assertRaisesRegex(RuntimeError, "plan_run_store_service"):
            await DefaultAgentRuntime(
                config=SimpleNamespace(),
                logging_gateway=Mock(),
                planning_engine_service=Mock(),
                evaluation_engine_service=Mock(),
                agent_executor_service=Mock(),
            ).run_background_batch(owner="worker")
        with self.assertRaisesRegex(ValueError, "Background owner is required"):
            configured = DefaultAgentRuntime(
                config=SimpleNamespace(),
                logging_gateway=Mock(),
                planning_engine_service=Mock(),
                evaluation_engine_service=Mock(),
                agent_executor_service=Mock(),
                plan_run_store_service=Mock(),
            )
            await configured.run_background_batch(owner=" ")

    async def test_agent_runtime_background_batch_skips_unleased_runs(self) -> None:
        due_run = _run(mode=PlanRunMode.BACKGROUND, request=_request(mode=PlanRunMode.BACKGROUND))
        runtime = DefaultAgentRuntime(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
            planning_engine_service=Mock(),
            evaluation_engine_service=Mock(),
            agent_executor_service=Mock(),
            plan_run_store_service=Mock(),
        )
        runtime._plan_run_store_service.list_runnable_runs = AsyncMock(return_value=[due_run])  # pylint: disable=protected-access
        runtime._plan_run_store_service.acquire_lease = AsyncMock(return_value=None)  # pylint: disable=protected-access

        outcomes = await runtime.run_background_batch(owner="worker")

        self.assertEqual(outcomes, [])

    async def test_agent_runtime_background_batch_releases_lease_when_refresh_fails(
        self,
    ) -> None:
        due_run = _run(mode=PlanRunMode.BACKGROUND, request=_request(mode=PlanRunMode.BACKGROUND))
        plan_run_store = Mock()
        plan_run_store.list_runnable_runs = AsyncMock(return_value=[due_run])
        plan_run_store.acquire_lease = AsyncMock(
            return_value=SimpleNamespace(owner="worker")
        )
        plan_run_store.load_run = AsyncMock(return_value=None)
        plan_run_store.release_lease = AsyncMock()
        runtime = DefaultAgentRuntime(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
            planning_engine_service=Mock(),
            evaluation_engine_service=Mock(),
            agent_executor_service=Mock(),
            plan_run_store_service=plan_run_store,
        )

        with self.assertRaisesRegex(RuntimeError, "lease acquisition"):
            await runtime.run_background_batch(owner="worker")

        plan_run_store.release_lease.assert_awaited_once_with(
            run_id=due_run.run_id,
            owner="worker",
        )

    async def test_reload_run_handle_returns_existing_run_without_load_run(self) -> None:
        run = _run()
        runtime = DefaultAgentRuntime(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
            plan_run_store_service=SimpleNamespace(),
        )

        refreshed_run = await runtime._reload_run_handle(  # pylint: disable=protected-access
            run,
            operation="test refresh",
        )

        self.assertIs(refreshed_run, run)

    async def test_agent_runtime_multi_agent_helper_edges(self) -> None:
        runtime = DefaultAgentRuntime(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
            planning_engine_service=Mock(
                prepare_run=AsyncMock(
                    side_effect=[
                        _run(
                            run_id="child-optional",
                            mode=PlanRunMode.BACKGROUND,
                            request=_request(mode=PlanRunMode.BACKGROUND),
                            status=PlanRunStatus.PREPARED,
                        )
                    ]
                )
            ),
            evaluation_engine_service=Mock(),
            agent_executor_service=Mock(
                list_capabilities=AsyncMock(return_value=[]),
                execute_capability=AsyncMock(),
            ),
            plan_run_store_service=Mock(
                save_run=AsyncMock(side_effect=lambda prepared_run: prepared_run),
                append_step=AsyncMock(side_effect=_append_cursor_side_effect()),
                finalize_run=AsyncMock(side_effect=lambda *, run_id, outcome: outcome),
                list_child_runs=AsyncMock(
                    return_value=[
                        _run(
                            run_id="child-pending",
                            mode=PlanRunMode.BACKGROUND,
                            request=_request(mode=PlanRunMode.BACKGROUND),
                            status=PlanRunStatus.PREPARED,
                        )
                    ]
                ),
            ),
        )

        runtime._bootstrap_observations = AsyncMock(  # pylint: disable=protected-access
            return_value=((), PlanOutcome(status=PlanOutcomeStatus.WAITING), False)
        )
        early = await runtime._run_loop(  # pylint: disable=protected-access
            request=_request(prepared_context=_prepared_context()),
            run=_run(),
            max_iterations=1,
            allow_wait=False,
        )
        self.assertEqual(early.status, PlanOutcomeStatus.WAITING)

        delegate_runtime = DefaultAgentRuntime(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
            planning_engine_service=Mock(
                next_decision=AsyncMock(return_value=PlanDecision(kind=PlanDecisionKind.DELEGATE)),
                finalize_run=AsyncMock(side_effect=lambda *_args: _run()),
            ),
            evaluation_engine_service=Mock(),
            agent_executor_service=Mock(),
            plan_run_store_service=Mock(
                save_run=AsyncMock(side_effect=lambda prepared_run: prepared_run),
                append_step=AsyncMock(side_effect=_append_cursor_side_effect()),
                finalize_run=AsyncMock(side_effect=lambda *, run_id, outcome: outcome),
            ),
        )
        delegated_handoff = await delegate_runtime._run_loop(  # pylint: disable=protected-access
            request=_request(mode=PlanRunMode.BACKGROUND),
            run=_run(mode=PlanRunMode.BACKGROUND, request=_request(mode=PlanRunMode.BACKGROUND)),
            max_iterations=1,
            allow_wait=True,
        )
        self.assertEqual(delegated_handoff.error_message, "delegate_requires_child_instructions")

        iterated_run = _run(
            mode=PlanRunMode.BACKGROUND,
            request=_request(mode=PlanRunMode.BACKGROUND),
        )
        iterated_run.state.iteration_count = 1
        self.assertEqual(
            await runtime._initial_request_observations(  # pylint: disable=protected-access
                request=_request(
                    mode=PlanRunMode.BACKGROUND,
                    metadata={"delegation": {"task_brief": "ignored"}},
                ),
                run=iterated_run,
            ),
            [],
        )

        delegated_request = _request(
            mode=PlanRunMode.BACKGROUND,
            metadata={
                "delegation": {
                    "task_brief": "",
                    "parent_run_id": "run-parent",
                    "parent_agent_key": "coordinator.root",
                    "delegated_agent_key": "specialist.lookup",
                    "required": False,
                    "artifacts": [
                        {
                            "artifact_key": "artifact.summary",
                            "source_run_id": "run-parent",
                            "summary": "facts",
                            "payload": {"value": 42},
                            "metadata": {"source": "parent"},
                        },
                        "ignored",
                    ],
                    "metadata": {"priority": "low"},
                }
            },
        )
        seeded = await runtime._initial_request_observations(  # pylint: disable=protected-access
            request=delegated_request,
            run=_run(
                mode=PlanRunMode.BACKGROUND,
                request=delegated_request,
                status=PlanRunStatus.PREPARED,
            ),
        )
        self.assertEqual(seeded[0].summary, "delegated_task")
        self.assertEqual(seeded[1].kind, "delegation_artifact")

        no_join = await runtime._resume_join_state(  # pylint: disable=protected-access
            request=_request(mode=PlanRunMode.BACKGROUND),
            run=_run(
                mode=PlanRunMode.BACKGROUND,
                request=_request(mode=PlanRunMode.BACKGROUND),
            ),
        )
        self.assertEqual(no_join, ((), None, False))

        waiting_run = _run(
            run_id="run-waiting",
            mode=PlanRunMode.BACKGROUND,
            request=_request(mode=PlanRunMode.BACKGROUND),
            status=PlanRunStatus.WAITING,
        )
        waiting_run.join_state = JoinState(
            child_run_ids=("child-pending",),
            required_child_run_ids=("child-pending",),
            timeout_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        observations, outcome, finalize_pending = await runtime._resume_join_state(  # pylint: disable=protected-access
            request=_request(mode=PlanRunMode.BACKGROUND),
            run=waiting_run,
        )
        self.assertEqual(observations, ())
        self.assertEqual(outcome.status, PlanOutcomeStatus.HANDOFF)
        self.assertEqual(outcome.error_message, "join_timeout_elapsed")
        self.assertEqual(
            outcome.metadata["waiting_on_child_run_ids"],
            ["child-pending"],
        )
        self.assertTrue(finalize_pending)

        still_waiting_run = _run(
            run_id="run-still-waiting",
            mode=PlanRunMode.BACKGROUND,
            request=_request(mode=PlanRunMode.BACKGROUND),
            status=PlanRunStatus.WAITING,
        )
        still_waiting_run.join_state = JoinState(
            child_run_ids=("child-pending",),
            required_child_run_ids=("child-pending",),
        )
        observations, outcome, finalize_pending = await runtime._resume_join_state(  # pylint: disable=protected-access
            request=_request(mode=PlanRunMode.BACKGROUND),
            run=still_waiting_run,
        )
        self.assertEqual(observations, ())
        self.assertEqual(outcome.status, PlanOutcomeStatus.WAITING)
        self.assertFalse(finalize_pending)
        self.assertEqual(
            outcome.metadata["waiting_on_child_run_ids"],
            ["child-pending"],
        )
        self.assertEqual(still_waiting_run.status, PlanRunStatus.WAITING)

        timeout_at = datetime.now(timezone.utc)
        self.assertIsNone(
            runtime._join_timeout_at(None)  # pylint: disable=protected-access
        )
        self.assertEqual(
            runtime._join_timeout_at(  # pylint: disable=protected-access
                JoinPolicy(metadata={"timeout_at": timeout_at})
            ),
            timeout_at,
        )
        self.assertEqual(
            runtime._join_timeout_at(  # pylint: disable=protected-access
                JoinPolicy(metadata={"timeout_at": timeout_at.isoformat()})
            ),
            timeout_at,
        )
        self.assertIsNone(
            runtime._join_timeout_at(  # pylint: disable=protected-access
                JoinPolicy(metadata={"timeout_seconds": True})
            )
        )

        self.assertIsNone(
            runtime._terminal_outcome_from_join_state(  # pylint: disable=protected-access
                join_state=JoinState(required_child_run_ids=("missing",)),
                child_runs={},
            )
        )
        self.assertEqual(
            runtime._terminal_outcome_from_join_state(  # pylint: disable=protected-access
                join_state=JoinState(required_child_run_ids=("child",)),
                child_runs={
                    "child": _run(
                        run_id="child",
                        mode=PlanRunMode.BACKGROUND,
                        request=_request(mode=PlanRunMode.BACKGROUND),
                        status=PlanRunStatus.HANDOFF,
                    )
                },
            ).error_message,
            "required_child_handoff",
        )
        self.assertEqual(
            runtime._terminal_outcome_from_join_state(  # pylint: disable=protected-access
                join_state=JoinState(required_child_run_ids=("child",)),
                child_runs={
                    "child": _run(
                        run_id="child",
                        mode=PlanRunMode.BACKGROUND,
                        request=_request(mode=PlanRunMode.BACKGROUND),
                        status=PlanRunStatus.STOPPED,
                    )
                },
            ).error_message,
            "required_child_stopped",
        )

        with self.assertRaisesRegex(RuntimeError, "delegate_requires_child_instructions"):
            await runtime._delegate_to_children(  # pylint: disable=protected-access
                request=_request(mode=PlanRunMode.BACKGROUND),
                run=_run(
                    mode=PlanRunMode.BACKGROUND,
                    request=_request(mode=PlanRunMode.BACKGROUND),
                    policy=AgentRuntimePolicy(
                        enabled=True,
                        background_enabled=True,
                        agent_key="coordinator.root",
                        delegate_agent_allow=("specialist.lookup",),
                    ),
                ),
                decision=PlanDecision(kind=PlanDecisionKind.DELEGATE),
            )

        with self.assertRaisesRegex(RuntimeError, "delegate_agent_not_allowed:blocked.agent"):
            await runtime._delegate_to_children(  # pylint: disable=protected-access
                request=_request(mode=PlanRunMode.BACKGROUND),
                run=_run(
                    mode=PlanRunMode.BACKGROUND,
                    request=_request(mode=PlanRunMode.BACKGROUND),
                    policy=AgentRuntimePolicy(
                        enabled=True,
                        background_enabled=True,
                        agent_key="coordinator.root",
                        delegate_agent_allow=("specialist.lookup",),
                    ),
                ),
                decision=PlanDecision(
                    kind=PlanDecisionKind.DELEGATE,
                    delegations=(
                        DelegationInstruction(
                            agent_key="blocked.agent",
                            task_brief="blocked",
                        ),
                    ),
                ),
            )

        optional_run = _run(
            run_id="run-optional",
            mode=PlanRunMode.BACKGROUND,
            request=_request(mode=PlanRunMode.BACKGROUND),
            policy=AgentRuntimePolicy(
                enabled=True,
                background_enabled=True,
                agent_key="coordinator.root",
                delegate_agent_allow=("specialist.lookup",),
            ),
        )
        optional_outcome = await runtime._delegate_to_children(  # pylint: disable=protected-access
            request=_request(mode=PlanRunMode.BACKGROUND),
            run=optional_run,
            decision=PlanDecision(
                kind=PlanDecisionKind.DELEGATE,
                join_policy=JoinPolicy(metadata={"timeout_seconds": 30}),
                delegations=(
                    DelegationInstruction(
                        agent_key="specialist.lookup",
                        task_brief="optional task",
                        required=False,
                    ),
                ),
            ),
        )
        self.assertEqual(optional_outcome.status, PlanOutcomeStatus.WAITING)
        self.assertEqual(optional_run.join_state.required_child_run_ids, ())
        self.assertIsNotNone(optional_run.join_state.timeout_at)

    async def test_agent_runtime_run_loop_terminal_and_wait_paths(self) -> None:
        def _make_runtime(decision, *, allow_wait=False, eval_response=None):
            planning_engine = Mock()
            planning_engine.next_decision = AsyncMock(return_value=decision)
            planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: run)
            evaluation_engine = Mock()
            evaluation_engine.evaluate_step = AsyncMock()
            evaluation_engine.evaluate_response = AsyncMock(
                return_value=eval_response
                or EvaluationResult(status=EvaluationStatus.PASS)
            )
            executor = Mock()
            executor.execute_capability = AsyncMock()
            plan_run_store = Mock()
            plan_run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
            plan_run_store.append_step = AsyncMock(side_effect=_append_cursor_side_effect())
            plan_run_store.finalize_run = AsyncMock(
                side_effect=lambda *, run_id, outcome: outcome
            )
            runtime = DefaultAgentRuntime(
                config=SimpleNamespace(),
                logging_gateway=Mock(),
                planning_engine_service=planning_engine,
                evaluation_engine_service=evaluation_engine,
                agent_executor_service=executor,
                plan_run_store_service=plan_run_store,
            )
            return runtime, planning_engine, evaluation_engine, plan_run_store, allow_wait

        run = _run()
        request = _request(prepared_context=_prepared_context())

        runtime, *_ = _make_runtime(PlanDecision(kind=PlanDecisionKind.WAIT))
        wait_blocked = await runtime._run_loop(  # pylint: disable=protected-access
            request=request,
            run=run,
            max_iterations=1,
            allow_wait=False,
        )
        self.assertEqual(wait_blocked.error_message, "wait_not_allowed_in_current_turn")

        scheduler = Mock()
        wake_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        scheduler.schedule_wait = AsyncMock(return_value=wake_at)
        with _patch_registry(_registry(scheduler=scheduler)):
            runtime, *_ = _make_runtime(PlanDecision(kind=PlanDecisionKind.WAIT))
            waiting = await runtime._run_loop(  # pylint: disable=protected-access
                request=_request(mode=PlanRunMode.BACKGROUND, prepared_context=_prepared_context()),
                run=_run(
                    mode=PlanRunMode.BACKGROUND,
                    request=_request(mode=PlanRunMode.BACKGROUND),
                ),
                max_iterations=1,
                allow_wait=True,
            )
            self.assertEqual(waiting.status, PlanOutcomeStatus.WAITING)

        runtime, *_ = _make_runtime(
            PlanDecision(
                kind=PlanDecisionKind.HANDOFF,
                response_text="human help",
                handoff_reason="needs_human",
            )
        )
        handoff = await runtime._run_loop(  # pylint: disable=protected-access
            request=request,
            run=_run(),
            max_iterations=1,
            allow_wait=False,
        )
        self.assertEqual(handoff.status, PlanOutcomeStatus.HANDOFF)

        runtime, *_ = _make_runtime(
            PlanDecision(
                kind=PlanDecisionKind.STOP,
                response_text="stopped",
                handoff_reason="done",
            )
        )
        stopped = await runtime._run_loop(  # pylint: disable=protected-access
            request=request,
            run=_run(),
            max_iterations=1,
            allow_wait=False,
        )
        self.assertEqual(stopped.status, PlanOutcomeStatus.STOPPED)

        runtime, *_ = _make_runtime(
            PlanDecision(kind=PlanDecisionKind.RESPOND, response_text="draft"),
            eval_response=EvaluationResult(status=EvaluationStatus.FAIL),
        )
        failed = await runtime._run_loop(  # pylint: disable=protected-access
            request=request,
            run=_run(),
            max_iterations=1,
            allow_wait=False,
        )
        self.assertEqual(failed.error_message, "response_evaluation_blocked")

        runtime, *_ = _make_runtime(
            PlanDecision(kind=PlanDecisionKind.RESPOND, response_text="draft")
        )
        maxed = await runtime._run_loop(  # pylint: disable=protected-access
            request=request,
            run=_run(),
            max_iterations=0,
            allow_wait=False,
        )
        self.assertEqual(maxed.error_message, "max_iterations_exceeded")

    async def test_response_synthesis_trace_sinks_and_scheduler_listing(self) -> None:
        run = _run(
            policy=AgentRuntimePolicy(
                enabled=True,
                response_synthesizer_key="preferred",
            )
        )
        request = _request()
        planning_engine = Mock()
        planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: run)
        runtime = DefaultAgentRuntime(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
            planning_engine_service=planning_engine,
            evaluation_engine_service=Mock(),
            agent_executor_service=Mock(),
            plan_run_store_service=Mock(),
        )
        runtime._plan_run_store_service.append_step = AsyncMock(  # pylint: disable=protected-access
            side_effect=_append_cursor_side_effect()
        )
        runtime._plan_run_store_service.save_run = AsyncMock(  # pylint: disable=protected-access
            side_effect=lambda prepared_run: prepared_run
        )
        runtime._plan_run_store_service.load_run = AsyncMock(  # pylint: disable=protected-access
            side_effect=[run, run, None]
        )

        fallback_payloads = await runtime._synthesize_response(  # pylint: disable=protected-access
            request=request,
            run=run,
            decision=PlanDecision(
                kind=PlanDecisionKind.RESPOND,
                response_payloads=({"type": "text", "content": "payload"},),
            ),
        )
        fallback_completion = await runtime._synthesize_response(  # pylint: disable=protected-access
            request=request,
            run=run,
            decision=PlanDecision(
                kind=PlanDecisionKind.RESPOND,
                completion=CompletionResponse(content="completion text"),
            ),
        )
        fallback_empty = await runtime._synthesize_response(  # pylint: disable=protected-access
            request=request,
            run=run,
            decision=PlanDecision(
                kind=PlanDecisionKind.RESPOND,
                completion=CompletionResponse(content={"structured": True}),
            ),
        )
        fallback_none = await runtime._synthesize_response(  # pylint: disable=protected-access
            request=request,
            run=run,
            decision=PlanDecision(kind=PlanDecisionKind.RESPOND),
        )

        preferred = Mock()
        preferred.name = "preferred"
        preferred.synthesize = AsyncMock(
            return_value=[{"type": "text", "content": "synthesized"}]
        )
        trace_sink = Mock()
        trace_sink.record_step = AsyncMock(side_effect=RuntimeError("step trace boom"))
        trace_sink.record_outcome = AsyncMock(
            side_effect=RuntimeError("outcome trace boom")
        )
        scheduler = Mock()
        scheduler.due_run_ids = AsyncMock(return_value=[run.run_id, "missing"])
        with _patch_registry(
            _registry(
                response_synthesizers=[preferred],
                trace_sinks=[trace_sink],
                scheduler=scheduler,
            )
        ):
            synthesized = await runtime._synthesize_response(  # pylint: disable=protected-access
                request=request,
                run=run,
                decision=PlanDecision(kind=PlanDecisionKind.RESPOND, response_text="hi"),
            )
            await runtime._append_step(  # pylint: disable=protected-access
                request=request,
                run=run,
                step_kind=PlanRunStepKind.EFFECT,
                payload={"ok": True},
            )
            await runtime._record_outcome(  # pylint: disable=protected-access
                request=request,
                run=run,
                outcome=PlanOutcome(status=PlanOutcomeStatus.COMPLETED),
            )
            due_runs = await runtime._list_due_runs(limit=2, now=None)  # pylint: disable=protected-access

        self.assertEqual(fallback_payloads[0]["content"], "payload")
        self.assertEqual(fallback_completion[0]["content"], "completion text")
        self.assertEqual(fallback_empty, [])
        self.assertEqual(fallback_none, [])
        self.assertEqual(synthesized[0]["content"], "synthesized")
        self.assertEqual([item.run_id for item in due_runs], [run.run_id])
        runtime._logging_gateway.warning.assert_called()  # pylint: disable=protected-access

        with _patch_registry(_registry(response_synthesizers=[preferred])):
            selected = runtime._select_response_synthesizer(  # pylint: disable=protected-access
                AgentRuntimePolicy(response_synthesizer_key="missing")
            )
            self.assertIs(selected, preferred)
            selected_default = runtime._select_response_synthesizer(  # pylint: disable=protected-access
                AgentRuntimePolicy(response_synthesizer_key="")
            )
            self.assertIs(selected_default, preferred)

        with _patch_registry(_registry()):
            direct_wait = await runtime._mark_waiting(  # pylint: disable=protected-access
                request=request,
                run=_run(
                    mode=PlanRunMode.BACKGROUND,
                    request=_request(mode=PlanRunMode.BACKGROUND),
                ),
                decision=PlanDecision(
                    kind=PlanDecisionKind.WAIT,
                    wait_until=datetime.now(timezone.utc) + timedelta(minutes=1),
                ),
            )
            self.assertEqual(direct_wait.status, PlanOutcomeStatus.WAITING)


if __name__ == "__main__":
    unittest.main()
