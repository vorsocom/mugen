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
    DelegationInstruction,
    EvaluationResult,
    EvaluationStatus,
    JoinPolicy,
    JoinState,
    PlanDecision,
    PlanDecisionKind,
    PlanLease,
    PlanOutcome,
    PlanOutcomeStatus,
    PlanRunCursor,
    PlanRunLineage,
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

    async def test_run_current_turn_rejects_delegate_decision(self) -> None:
        request = _request(prepared_context=_prepared_context())
        run = _run(request=request)
        planning_engine = Mock()
        planning_engine.prepare_run = AsyncMock(return_value=run)
        planning_engine.next_decision = AsyncMock(
            return_value=PlanDecision(
                kind=PlanDecisionKind.DELEGATE,
                delegations=(
                    DelegationInstruction(
                        agent_key="specialist.lookup",
                        task_brief="Investigate this",
                    ),
                ),
            )
        )
        planning_engine.finalize_run = AsyncMock(side_effect=lambda *_args: run)

        runtime = _runtime(
            planning_engine=planning_engine,
            evaluation_engine=Mock(),
            executor=Mock(
                list_capabilities=AsyncMock(return_value=[]),
                execute_capability=AsyncMock(),
            ),
            plan_run_store=Mock(
                save_run=AsyncMock(side_effect=lambda prepared_run: prepared_run),
                append_step=AsyncMock(side_effect=_append_cursor_side_effect()),
                finalize_run=AsyncMock(side_effect=lambda *, run_id, outcome: outcome),
            ),
        )

        outcome = await runtime.run_current_turn(request)

        self.assertEqual(outcome.status, PlanOutcomeStatus.HANDOFF)
        self.assertEqual(outcome.error_message, "delegate_not_allowed_in_current_turn")

    async def test_run_background_batch_delegates_waits_and_resumes_on_child_completion(self) -> None:
        parent_request = _request(
            mode=PlanRunMode.BACKGROUND,
            agent_key="coordinator.root",
        )
        parent_run = _run(
            run_id="run-parent",
            mode=PlanRunMode.BACKGROUND,
            request=parent_request,
            policy=AgentRuntimePolicy(
                enabled=True,
                background_enabled=True,
                agent_key="coordinator.root",
                delegate_agent_allow=("specialist.lookup",),
                max_background_iterations=4,
            ),
        )
        child_run = _run(
            run_id="run-child",
            mode=PlanRunMode.BACKGROUND,
            request=_request(
                mode=PlanRunMode.BACKGROUND,
                service_route_key="support.lookup",
                agent_key="specialist.lookup",
            ),
            policy=AgentRuntimePolicy(
                enabled=True,
                background_enabled=True,
                agent_key="specialist.lookup",
            ),
            status=PlanRunStatus.PREPARED,
        )
        child_run.lineage = PlanRunLineage(
            parent_run_id="run-parent",
            root_run_id="run-parent",
            spawned_by_step_no=1,
            agent_key="specialist.lookup",
        )
        child_completed = _run(
            run_id="run-child",
            mode=PlanRunMode.BACKGROUND,
            request=_request(
                mode=PlanRunMode.BACKGROUND,
                service_route_key="support.lookup",
                agent_key="specialist.lookup",
            ),
            policy=child_run.policy,
            status=PlanRunStatus.COMPLETED,
        )
        child_completed.lineage = child_run.lineage
        child_completed.final_outcome = PlanOutcome(
            status=PlanOutcomeStatus.COMPLETED,
            assistant_response="lookup complete",
        )

        parent_waiting = _run(
            run_id="run-parent",
            mode=PlanRunMode.BACKGROUND,
            request=parent_request,
            policy=parent_run.policy,
            status=PlanRunStatus.WAITING,
        )
        parent_waiting.lineage = PlanRunLineage(
            root_run_id="run-parent",
            agent_key="coordinator.root",
        )
        parent_waiting.join_state = JoinState(
            child_run_ids=("run-child",),
            required_child_run_ids=("run-child",),
            policy=JoinPolicy(),
        )

        planning_engine = Mock()
        planning_engine.prepare_run = AsyncMock(side_effect=[child_run])
        planning_engine.next_decision = AsyncMock(
            side_effect=[
                PlanDecision(
                    kind=PlanDecisionKind.DELEGATE,
                    delegations=(
                        DelegationInstruction(
                            agent_key="specialist.lookup",
                            task_brief="Look this up",
                            service_route_key="support.lookup",
                        ),
                    ),
                    join_policy=JoinPolicy(),
                ),
                PlanDecision(
                    kind=PlanDecisionKind.RESPOND,
                    response_text="Final after child",
                ),
            ]
        )
        planning_engine.finalize_run = AsyncMock(
            side_effect=lambda *_args: parent_waiting
        )

        evaluation_engine = Mock()
        evaluation_engine.evaluate_step = AsyncMock()
        evaluation_engine.evaluate_response = AsyncMock(
            return_value=EvaluationResult(status=EvaluationStatus.PASS)
        )

        executor = Mock()
        executor.list_capabilities = AsyncMock(return_value=[])
        executor.execute_capability = AsyncMock()

        plan_run_store = Mock()
        plan_run_store.list_runnable_runs = AsyncMock(
            side_effect=[[parent_run], [parent_waiting]]
        )
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
        plan_run_store.load_run = AsyncMock(side_effect=[parent_run, parent_waiting])
        plan_run_store.list_child_runs = AsyncMock(return_value=[child_completed])
        plan_run_store.load_run_graph = AsyncMock(return_value=[parent_waiting, child_completed])

        runtime = _runtime(
            planning_engine=planning_engine,
            evaluation_engine=evaluation_engine,
            executor=executor,
            plan_run_store=plan_run_store,
        )

        first_outcomes = await runtime.run_background_batch(owner="worker-1", limit=10)
        second_outcomes = await runtime.run_background_batch(owner="worker-1", limit=10)

        self.assertEqual(first_outcomes[0].status, PlanOutcomeStatus.WAITING)
        self.assertEqual(second_outcomes[0].status, PlanOutcomeStatus.COMPLETED)
        self.assertEqual(second_outcomes[0].assistant_response, "Final after child")
        self.assertEqual(planning_engine.prepare_run.await_count, 1)
        self.assertEqual(planning_engine.next_decision.await_count, 2)
        self.assertGreaterEqual(plan_run_store.list_child_runs.await_count, 1)

    async def test_run_background_batch_handoffs_when_required_child_fails(self) -> None:
        parent_request = _request(
            mode=PlanRunMode.BACKGROUND,
            agent_key="coordinator.root",
        )
        parent_run = _run(
            run_id="run-parent",
            mode=PlanRunMode.BACKGROUND,
            request=parent_request,
            policy=AgentRuntimePolicy(
                enabled=True,
                background_enabled=True,
                agent_key="coordinator.root",
            ),
            status=PlanRunStatus.WAITING,
        )
        parent_run.lineage = PlanRunLineage(
            root_run_id="run-parent",
            agent_key="coordinator.root",
        )
        parent_run.join_state = JoinState(
            child_run_ids=("run-child",),
            required_child_run_ids=("run-child",),
            policy=JoinPolicy(),
        )
        failed_child = _run(
            run_id="run-child",
            mode=PlanRunMode.BACKGROUND,
            request=_request(
                mode=PlanRunMode.BACKGROUND,
                agent_key="specialist.lookup",
            ),
            status=PlanRunStatus.FAILED,
        )
        failed_child.lineage = PlanRunLineage(
            parent_run_id="run-parent",
            root_run_id="run-parent",
            agent_key="specialist.lookup",
        )
        failed_child.final_outcome = PlanOutcome(
            status=PlanOutcomeStatus.FAILED,
            error_message="child failed",
        )

        runtime = _runtime(
            planning_engine=Mock(
                prepare_run=AsyncMock(),
                next_decision=AsyncMock(),
                finalize_run=AsyncMock(side_effect=lambda *_args: parent_run),
            ),
            evaluation_engine=Mock(),
            executor=Mock(
                list_capabilities=AsyncMock(return_value=[]),
                execute_capability=AsyncMock(),
            ),
            plan_run_store=Mock(
                list_runnable_runs=AsyncMock(return_value=[parent_run]),
                acquire_lease=AsyncMock(
                    return_value=PlanLease(
                        owner="worker-1",
                        expires_at=datetime.now(timezone.utc),
                    )
                ),
                release_lease=AsyncMock(),
                save_run=AsyncMock(side_effect=lambda prepared_run: prepared_run),
                append_step=AsyncMock(side_effect=_append_cursor_side_effect()),
                finalize_run=AsyncMock(side_effect=lambda *, run_id, outcome: outcome),
                load_run=AsyncMock(return_value=parent_run),
                list_child_runs=AsyncMock(return_value=[failed_child]),
                load_run_graph=AsyncMock(return_value=[parent_run, failed_child]),
            ),
        )

        outcomes = await runtime.run_background_batch(owner="worker-1", limit=10)

        self.assertEqual(outcomes[0].status, PlanOutcomeStatus.HANDOFF)
        self.assertEqual(outcomes[0].error_message, "required_child_failed")


if __name__ == "__main__":
    unittest.main()
