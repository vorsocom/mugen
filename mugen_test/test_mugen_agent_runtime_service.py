"""Service tests for the core agent-runtime orchestration layer."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.agent import (
    AgentRuntimePolicy,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityResult,
    EvaluationResult,
    EvaluationStatus,
    PlanDecision,
    PlanDecisionKind,
    PlanLease,
    PlanOutcome,
    PlanOutcomeStatus,
    PlanRunCursor,
    PlanRunMode,
    PlanRunRequest,
    PlanRunState,
    PlanRunStatus,
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
)
import mugen.core.service.agent_runtime as agent_runtime_module
from mugen.core.service.agent_runtime import DefaultAgentRuntime


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
            messages=[
                CompletionMessage(role="system", content="Be helpful."),
                CompletionMessage(role="user", content="hello"),
            ]
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
    run_id: str | None = None,
) -> PlanRunRequest:
    return PlanRunRequest(
        mode=mode,
        scope=_scope(),
        user_message="Handle the request",
        service_route_key="support.primary",
        prepared_context=prepared_context,
        run_id=run_id,
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
            "ingress_metadata": dict(resolved_request.ingress_metadata),
            "metadata": dict(resolved_request.metadata),
        },
        cursor=PlanRunCursor(run_id=run_id),
        service_route_key=resolved_request.service_route_key,
        row_version=1,
    )


def _append_cursor_side_effect():
    async def _append_step(*, run_id: str, step) -> PlanRunCursor:
        return PlanRunCursor(
            run_id=run_id,
            next_sequence_no=step.sequence_no + 1,
            status=PlanRunStatus.ACTIVE,
        )

    return _append_step


def _runtime(
    *,
    planning_engine,
    evaluation_engine,
    executor,
    plan_run_store,
) -> DefaultAgentRuntime:
    return DefaultAgentRuntime(
        config=SimpleNamespace(),
        logging_gateway=Mock(),
        planning_engine_service=planning_engine,
        evaluation_engine_service=evaluation_engine,
        agent_executor_service=executor,
        plan_run_store_service=plan_run_store,
    )


class TestMugenAgentRuntimeService(unittest.IsolatedAsyncioTestCase):
    """Exercise current-turn and background orchestration loops."""

    async def asyncSetUp(self) -> None:
        self._container_patch = patch.object(
            agent_runtime_module.di,
            "container",
            new=SimpleNamespace(
                get_ext_service=lambda _name, default=None: default,
            ),
        )
        self._container_patch.start()

    async def asyncTearDown(self) -> None:
        self._container_patch.stop()

    async def test_run_current_turn_executes_capability_loop_and_completes(self) -> None:
        request = _request(prepared_context=_prepared_context())
        run = _run(request=request)
        planning_engine = Mock()
        planning_engine.prepare_run = AsyncMock(return_value=run)
        planning_engine.next_decision = AsyncMock(
            side_effect=[
                PlanDecision(
                    kind=PlanDecisionKind.EXECUTE_ACTION,
                    capability_invocations=(
                        CapabilityInvocation(capability_key="cap.lookup"),
                    ),
                ),
                PlanDecision(
                    kind=PlanDecisionKind.RESPOND,
                    response_text="final answer",
                ),
            ]
        )
        planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: run)

        evaluation_engine = Mock()
        evaluation_engine.evaluate_step = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )
        evaluation_engine.evaluate_response = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )

        executor = Mock()
        executor.list_capabilities = AsyncMock(
            return_value=[
                CapabilityDescriptor(key="cap.lookup", title="Lookup capability")
            ]
        )
        executor.execute_capability = AsyncMock(
            return_value=CapabilityResult(
                capability_key="cap.lookup",
                ok=True,
                result={"answer": "42"},
            )
        )

        plan_run_store = Mock()
        plan_run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
        plan_run_store.append_step = AsyncMock(side_effect=_append_cursor_side_effect())
        plan_run_store.finalize_run = AsyncMock(
            side_effect=lambda *, run_id, outcome: outcome
        )

        runtime = _runtime(
            planning_engine=planning_engine,
            evaluation_engine=evaluation_engine,
            executor=executor,
            plan_run_store=plan_run_store,
        )

        outcome = await runtime.run_current_turn(request)

        self.assertEqual(outcome.status, PlanOutcomeStatus.COMPLETED)
        self.assertEqual(outcome.assistant_response, "final answer")
        executor.execute_capability.assert_awaited_once()
        self.assertGreaterEqual(plan_run_store.append_step.await_count, 5)
        planning_engine.finalize_run.assert_awaited_once()

    async def test_run_current_turn_retries_after_step_evaluation_retry(self) -> None:
        request = _request(prepared_context=_prepared_context())
        run = _run(request=request)
        planning_engine = Mock()
        planning_engine.prepare_run = AsyncMock(return_value=run)
        planning_engine.next_decision = AsyncMock(
            side_effect=[
                PlanDecision(
                    kind=PlanDecisionKind.EXECUTE_ACTION,
                    capability_invocations=(
                        CapabilityInvocation(capability_key="cap.lookup"),
                    ),
                ),
                PlanDecision(
                    kind=PlanDecisionKind.RESPOND,
                    response_text="retried answer",
                ),
            ]
        )
        planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: run)

        evaluation_engine = Mock()
        evaluation_engine.evaluate_step = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.RETRY)
        )
        evaluation_engine.evaluate_response = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )

        executor = Mock()
        executor.list_capabilities = AsyncMock(
            return_value=[CapabilityDescriptor(key="cap.lookup", title="Lookup")]
        )
        executor.execute_capability = AsyncMock(
            return_value=CapabilityResult(capability_key="cap.lookup", ok=True)
        )

        plan_run_store = Mock()
        plan_run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
        plan_run_store.append_step = AsyncMock(side_effect=_append_cursor_side_effect())
        plan_run_store.finalize_run = AsyncMock(
            side_effect=lambda *, run_id, outcome: outcome
        )

        runtime = _runtime(
            planning_engine=planning_engine,
            evaluation_engine=evaluation_engine,
            executor=executor,
            plan_run_store=plan_run_store,
        )

        outcome = await runtime.run_current_turn(request)

        self.assertEqual(outcome.status, PlanOutcomeStatus.COMPLETED)
        self.assertEqual(outcome.assistant_response, "retried answer")
        self.assertEqual(planning_engine.next_decision.await_count, 2)

    async def test_run_current_turn_replans_after_response_evaluation_replan(self) -> None:
        request = _request(prepared_context=_prepared_context())
        run = _run(request=request)
        planning_engine = Mock()
        planning_engine.prepare_run = AsyncMock(return_value=run)
        planning_engine.next_decision = AsyncMock(
            side_effect=[
                PlanDecision(kind=PlanDecisionKind.RESPOND, response_text="first"),
                PlanDecision(kind=PlanDecisionKind.RESPOND, response_text="second"),
            ]
        )
        planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: run)

        evaluation_engine = Mock()
        evaluation_engine.evaluate_step = AsyncMock()
        evaluation_engine.evaluate_response = AsyncMock(
            side_effect=[
                EvaluationResult(status=EvaluationStatus.REPLAN),
                EvaluationResult(status=EvaluationStatus.PASS),
            ]
        )

        executor = Mock()
        executor.list_capabilities = AsyncMock(return_value=[])
        executor.execute_capability = AsyncMock()

        plan_run_store = Mock()
        plan_run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
        plan_run_store.append_step = AsyncMock(side_effect=_append_cursor_side_effect())
        plan_run_store.finalize_run = AsyncMock(
            side_effect=lambda *, run_id, outcome: outcome
        )

        runtime = _runtime(
            planning_engine=planning_engine,
            evaluation_engine=evaluation_engine,
            executor=executor,
            plan_run_store=plan_run_store,
        )

        outcome = await runtime.run_current_turn(request)

        self.assertEqual(outcome.status, PlanOutcomeStatus.COMPLETED)
        self.assertEqual(outcome.assistant_response, "second")
        self.assertEqual(planning_engine.next_decision.await_count, 2)

    async def test_run_current_turn_handoffs_when_evaluator_escalates(self) -> None:
        request = _request(prepared_context=_prepared_context())
        run = _run(request=request)
        planning_engine = Mock()
        planning_engine.prepare_run = AsyncMock(return_value=run)
        planning_engine.next_decision = AsyncMock(
            return_value=PlanDecision(
                kind=PlanDecisionKind.EXECUTE_ACTION,
                capability_invocations=(
                    CapabilityInvocation(capability_key="cap.lookup"),
                ),
            )
        )
        planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: run)

        evaluation_engine = Mock()
        evaluation_engine.evaluate_step = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.ESCALATE)
        )
        evaluation_engine.evaluate_response = AsyncMock()

        executor = Mock()
        executor.list_capabilities = AsyncMock(
            return_value=[CapabilityDescriptor(key="cap.lookup", title="Lookup")]
        )
        executor.execute_capability = AsyncMock(
            return_value=CapabilityResult(capability_key="cap.lookup", ok=False)
        )

        plan_run_store = Mock()
        plan_run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
        plan_run_store.append_step = AsyncMock(side_effect=_append_cursor_side_effect())
        plan_run_store.finalize_run = AsyncMock(
            side_effect=lambda *, run_id, outcome: outcome
        )

        runtime = _runtime(
            planning_engine=planning_engine,
            evaluation_engine=evaluation_engine,
            executor=executor,
            plan_run_store=plan_run_store,
        )

        outcome = await runtime.run_current_turn(request)

        self.assertEqual(outcome.status, PlanOutcomeStatus.HANDOFF)
        self.assertEqual(outcome.error_message, "step_evaluation_blocked")

    async def test_run_current_turn_spawns_background_follow_up(self) -> None:
        current_request = _request(prepared_context=_prepared_context())
        current_run = _run(run_id="run-current", request=current_request)
        background_request = _request(mode=PlanRunMode.BACKGROUND)
        background_run = _run(
            run_id="run-background",
            mode=PlanRunMode.BACKGROUND,
            request=background_request,
        )
        planning_engine = Mock()
        planning_engine.prepare_run = AsyncMock(
            side_effect=[current_run, background_run]
        )
        planning_engine.next_decision = AsyncMock(
            return_value=PlanDecision(
                kind=PlanDecisionKind.SPAWN_BACKGROUND,
                response_text="Working on it",
                background_payload={"user_message": "continue in background"},
            )
        )
        planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: current_run)

        evaluation_engine = Mock()
        evaluation_engine.evaluate_step = AsyncMock()
        evaluation_engine.evaluate_response = AsyncMock()

        executor = Mock()
        executor.list_capabilities = AsyncMock(return_value=[])
        executor.execute_capability = AsyncMock()

        plan_run_store = Mock()
        plan_run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
        plan_run_store.append_step = AsyncMock(side_effect=_append_cursor_side_effect())
        plan_run_store.finalize_run = AsyncMock(
            side_effect=lambda *, run_id, outcome: outcome
        )

        runtime = _runtime(
            planning_engine=planning_engine,
            evaluation_engine=evaluation_engine,
            executor=executor,
            plan_run_store=plan_run_store,
        )

        outcome = await runtime.run_current_turn(current_request)

        self.assertEqual(outcome.status, PlanOutcomeStatus.SPAWNED_BACKGROUND)
        self.assertEqual(outcome.background_run_id, "run-background")
        self.assertEqual(
            outcome.final_user_responses,
            ({"type": "text", "content": "Working on it"},),
        )
        self.assertEqual(planning_engine.prepare_run.await_count, 2)

    async def test_run_background_batch_resumes_due_runs_and_releases_lease(self) -> None:
        request = _request(mode=PlanRunMode.BACKGROUND)
        due_run = _run(
            run_id="run-background",
            mode=PlanRunMode.BACKGROUND,
            request=request,
        )
        planning_engine = Mock()
        planning_engine.prepare_run = AsyncMock()
        planning_engine.next_decision = AsyncMock(
            return_value=PlanDecision(
                kind=PlanDecisionKind.RESPOND,
                response_text="background answer",
            )
        )
        planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: due_run)

        evaluation_engine = Mock()
        evaluation_engine.evaluate_step = AsyncMock()
        evaluation_engine.evaluate_response = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )

        executor = Mock()
        executor.list_capabilities = AsyncMock(return_value=[])
        executor.execute_capability = AsyncMock()

        plan_run_store = Mock()
        plan_run_store.list_runnable_runs = AsyncMock(return_value=[due_run])
        plan_run_store.acquire_lease = AsyncMock(
            return_value=PlanLease(
                owner="worker-1",
                expires_at=datetime.now(timezone.utc),
            )
        )
        plan_run_store.release_lease = AsyncMock()
        plan_run_store.save_run = AsyncMock(side_effect=lambda prepared_run: prepared_run)
        plan_run_store.append_step = AsyncMock(side_effect=_append_cursor_side_effect())
        plan_run_store.finalize_run = AsyncMock(
            side_effect=lambda *, run_id, outcome: outcome
        )
        plan_run_store.load_run = AsyncMock(return_value=due_run)

        runtime = _runtime(
            planning_engine=planning_engine,
            evaluation_engine=evaluation_engine,
            executor=executor,
            plan_run_store=plan_run_store,
        )

        outcomes = await runtime.run_background_batch(owner="worker-1", limit=10)

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].status, PlanOutcomeStatus.COMPLETED)
        self.assertEqual(outcomes[0].assistant_response, "background answer")
        plan_run_store.acquire_lease.assert_awaited_once()
        plan_run_store.release_lease.assert_awaited_once_with(
            run_id="run-background",
            owner="worker-1",
        )


if __name__ == "__main__":
    unittest.main()
