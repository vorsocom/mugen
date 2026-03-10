"""Contract tests for agent-runtime IRs and seams."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from mugen.core.contract.agent import (
    AgentRuntimePolicy,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityResult,
    EvaluationRequest,
    EvaluationResult,
    EvaluationStatus,
    PlanDecision,
    PlanDecisionKind,
    PlanLease,
    PlanObservation,
    PlanOutcome,
    PlanOutcomeStatus,
    PlanRunCursor,
    PlanRunRequest,
    PlanRunMode,
    PlanRunState,
    PlanRunStatus,
    PlanRunStep,
    PreparedPlanRun,
)
from mugen.core.contract.context import ContextScope


def _scope() -> ContextScope:
    return ContextScope(
        tenant_id="tenant-1",
        platform="matrix",
        channel_id="matrix",
        room_id="room-1",
        sender_id="user-1",
        conversation_id="room-1",
    )


class TestMugenAgentContracts(unittest.TestCase):
    """Keep the new agent IRs deterministic and provider-neutral."""

    def test_plan_run_request_derives_service_route_key_from_ingress_metadata(self) -> None:
        request = PlanRunRequest(
            mode="current_turn",
            scope=_scope(),
            user_message="  hello  ",
            ingress_metadata={
                "ingress_route": {
                    "service_route_key": "  inbox.primary  ",
                }
            },
            available_capabilities=[
                CapabilityDescriptor(
                    key="cap.one",
                    title="Capability One",
                )
            ],
        )

        self.assertEqual(request.user_message, "hello")
        self.assertEqual(request.service_route_key, "inbox.primary")
        self.assertEqual(request.available_capabilities[0].key, "cap.one")
        self.assertEqual(type(request.available_capabilities), tuple)

    def test_capability_descriptor_requires_non_blank_identity(self) -> None:
        with self.assertRaises(ValueError):
            CapabilityDescriptor(key=" ", title="Title")

        with self.assertRaises(ValueError):
            CapabilityDescriptor(key="cap.one", title=" ")

        with self.assertRaises(TypeError):
            CapabilityDescriptor(key="cap.one", title="Title", description=123)

    def test_prepared_plan_run_and_evaluation_normalize_enums(self) -> None:
        prepared = PreparedPlanRun(
            run_id="run-1",
            mode="background",
            status="prepared",
            state=PlanRunState(goal="Investigate"),
            policy=AgentRuntimePolicy(enabled=True, background_enabled=True),
            request_snapshot={"mode": "background"},
            cursor=PlanRunCursor(run_id="run-1"),
            row_version=7,
            created_at=datetime.now(timezone.utc),
        )
        decision = PlanDecision(kind="respond", response_text="done")
        evaluation = EvaluationResult(
            status="retry",
            reasons=(" blank_response ", ""),
            recommended_decision="respond",
        )
        outcome = PlanOutcome(status="completed", assistant_response="done")

        self.assertEqual(prepared.mode.value, "background")
        self.assertEqual(prepared.status, PlanRunStatus.PREPARED)
        self.assertEqual(prepared.row_version, 7)
        self.assertEqual(decision.kind, PlanDecisionKind.RESPOND)
        self.assertEqual(evaluation.status, EvaluationStatus.RETRY)
        self.assertEqual(evaluation.reasons, ("blank_response",))
        self.assertEqual(outcome.status, PlanOutcomeStatus.COMPLETED)
        self.assertEqual(PlanRunState(goal="x", status="active").status, PlanRunStatus.ACTIVE)
        self.assertEqual(
            PlanRunCursor(run_id="run-2", status="waiting").status,
            PlanRunStatus.WAITING,
        )

    def test_contract_validation_guards_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            CapabilityInvocation(capability_key=" ")
        with self.assertRaises(TypeError):
            CapabilityInvocation(capability_key="cap.one", arguments="bad")

        with self.assertRaises(ValueError):
            CapabilityResult(capability_key=" ", ok=False)

        with self.assertRaises(TypeError):
            PlanRunRequest(mode="current_turn", scope="bad", user_message="hello")
        with self.assertRaises(ValueError):
            PlanRunRequest(mode="current_turn", scope=_scope(), user_message=" ")
        with self.assertRaises(TypeError):
            PlanRunRequest(
                mode="current_turn",
                scope=_scope(),
                user_message="hello",
                ingress_metadata="bad",
            )

        with self.assertRaises(ValueError):
            PlanRunState(goal=" ")

        with self.assertRaises(ValueError):
            PlanLease(owner=" ", expires_at=datetime.now(timezone.utc))
        with self.assertRaises(TypeError):
            PlanLease(owner="worker-1", expires_at="bad")

        with self.assertRaises(ValueError):
            PlanRunCursor(run_id=" ")

        with self.assertRaises(ValueError):
            PlanObservation(kind=" ")
        with self.assertRaises(TypeError):
            PlanObservation(kind="tool", payload="bad")

        valid_request = PlanRunRequest(
            mode="current_turn",
            scope=_scope(),
            user_message="hello",
        )
        valid_run = PreparedPlanRun(
            run_id="run-1",
            mode=PlanRunMode.CURRENT_TURN,
            status=PlanRunStatus.PREPARED,
            state=PlanRunState(goal="hello"),
            policy=AgentRuntimePolicy(),
            request_snapshot={},
            cursor=PlanRunCursor(run_id="run-1"),
        )
        with self.assertRaises(TypeError):
            EvaluationRequest(request="bad", run=valid_run)
        with self.assertRaises(TypeError):
            EvaluationRequest(request=valid_request, run="bad")

        with self.assertRaises(ValueError):
            PlanRunStep(run_id=" ", sequence_no=1, step_kind="decision")
        with self.assertRaises(TypeError):
            PlanRunStep(
                run_id="run-1",
                sequence_no=1,
                step_kind="decision",
                payload="bad",
            )

        with self.assertRaises(ValueError):
            PreparedPlanRun(
                run_id=" ",
                mode="current_turn",
                status="prepared",
                state=PlanRunState(goal="hello"),
                policy=AgentRuntimePolicy(),
                request_snapshot={},
                cursor=PlanRunCursor(run_id="run-1"),
            )
        with self.assertRaises(TypeError):
            PreparedPlanRun(
                run_id="run-1",
                mode="current_turn",
                status="prepared",
                state="bad",
                policy=AgentRuntimePolicy(),
                request_snapshot={},
                cursor=PlanRunCursor(run_id="run-1"),
            )
        with self.assertRaises(TypeError):
            PreparedPlanRun(
                run_id="run-1",
                mode="current_turn",
                status="prepared",
                state=PlanRunState(goal="hello"),
                policy="bad",
                request_snapshot={},
                cursor=PlanRunCursor(run_id="run-1"),
            )
        with self.assertRaises(TypeError):
            PreparedPlanRun(
                run_id="run-1",
                mode="current_turn",
                status="prepared",
                state=PlanRunState(goal="hello"),
                policy=AgentRuntimePolicy(),
                request_snapshot={},
                cursor="bad",
            )
        with self.assertRaises(TypeError):
            PreparedPlanRun(
                run_id="run-1",
                mode="current_turn",
                status="prepared",
                state=PlanRunState(goal="hello"),
                policy=AgentRuntimePolicy(),
                request_snapshot="bad",
                cursor=PlanRunCursor(run_id="run-1"),
            )


if __name__ == "__main__":
    unittest.main()
