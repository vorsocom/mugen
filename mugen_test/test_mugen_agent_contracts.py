"""Contract tests for agent-runtime IRs and seams."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

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
    PlanLease,
    PlanObservation,
    PlanOutcome,
    PlanOutcomeStatus,
    PlanRunCursor,
    PlanRunLineage,
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

    def test_multi_agent_contracts_normalize_lineage_and_delegation(self) -> None:
        lineage = PlanRunLineage(
            parent_run_id=" run-parent ",
            root_run_id=" run-root ",
            spawned_by_step_no=3,
            agent_key=" specialist.lookup ",
        )
        artifact = DelegationArtifactRef(
            artifact_key=" step.summary ",
            source_run_id=" run-parent ",
            source_step_sequence_no=2,
            summary=" facts ",
            payload={"answer": 42},
        )
        delegation = DelegationInstruction(
            agent_key=" specialist.lookup ",
            task_brief=" investigate account status ",
            artifacts=(artifact,),
        )
        decision = PlanDecision(
            kind="delegate",
            delegations=(delegation,),
            join_policy=JoinPolicy(),
        )
        request = PlanRunRequest(
            mode="background",
            scope=_scope(),
            user_message="delegate this",
            agent_key=" coordinator.root ",
        )

        self.assertEqual(lineage.parent_run_id, "run-parent")
        self.assertEqual(lineage.root_run_id, "run-root")
        self.assertEqual(lineage.agent_key, "specialist.lookup")
        self.assertEqual(artifact.artifact_key, "step.summary")
        self.assertEqual(delegation.task_brief, "investigate account status")
        self.assertEqual(decision.kind, PlanDecisionKind.DELEGATE)
        self.assertEqual(decision.delegations[0].agent_key, "specialist.lookup")
        self.assertEqual(request.agent_key, "coordinator.root")

    def test_join_policy_and_evaluation_result_normalize_enums(self) -> None:
        policy = JoinPolicy(
            mode="all_required",
            on_required_child_failed="failed",
            on_required_child_handoff="handoff",
            on_required_child_stopped="stopped",
        )
        result = EvaluationResult(
            status="retry",
            recommended_decision="delegate",
        )

        self.assertEqual(policy.mode.value, "all_required")
        self.assertEqual(policy.on_required_child_failed, PlanOutcomeStatus.FAILED)
        self.assertEqual(policy.on_required_child_handoff, PlanOutcomeStatus.HANDOFF)
        self.assertEqual(policy.on_required_child_stopped, PlanOutcomeStatus.STOPPED)
        self.assertEqual(result.recommended_decision, PlanDecisionKind.DELEGATE)

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
            policy=AgentRuntimePolicy(
                enabled=True,
                background_enabled=True,
                agent_key="coordinator.root",
                delegate_agent_allow=("specialist.lookup",),
            ),
            request_snapshot={"mode": "background"},
            cursor=PlanRunCursor(run_id="run-1"),
            lineage=PlanRunLineage(
                root_run_id="run-1",
                agent_key="coordinator.root",
            ),
            join_state=JoinState(
                child_run_ids=("child-1",),
                required_child_run_ids=("child-1",),
            ),
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
        self.assertEqual(prepared.lineage.root_run_id, "run-1")
        self.assertEqual(prepared.join_state.required_child_run_ids, ("child-1",))
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
        with self.assertRaises(TypeError):
            AgentRuntimePolicy(metadata="bad")

        with self.assertRaises(ValueError):
            CapabilityInvocation(capability_key=" ")
        with self.assertRaises(TypeError):
            CapabilityInvocation(capability_key="cap.one", arguments="bad")
        with self.assertRaises(TypeError):
            CapabilityInvocation(
                capability_key="cap.one",
                metadata="bad",
            )

        with self.assertRaises(ValueError):
            CapabilityResult(capability_key=" ", ok=False)
        with self.assertRaises(TypeError):
            CapabilityResult(capability_key="cap.one", ok=True, metadata="bad")

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
        with self.assertRaises(TypeError):
            PlanRunRequest(
                mode="current_turn",
                scope=_scope(),
                user_message="hello",
                metadata="bad",
            )

        with self.assertRaises(ValueError):
            PlanRunState(goal=" ")
        with self.assertRaises(TypeError):
            PlanRunState(goal="hello", metadata="bad")

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
        with self.assertRaises(TypeError):
            PlanObservation(kind="tool", metadata="bad")
        with self.assertRaises(ValueError):
            DelegationArtifactRef(artifact_key=" ", source_run_id="run-1")
        with self.assertRaises(ValueError):
            DelegationArtifactRef(artifact_key="artifact", source_run_id=" ")
        with self.assertRaises(TypeError):
            DelegationArtifactRef(
                artifact_key="artifact",
                source_run_id="run-1",
                payload="bad",
            )
        with self.assertRaises(TypeError):
            DelegationArtifactRef(
                artifact_key="artifact",
                source_run_id="run-1",
                metadata="bad",
            )
        with self.assertRaises(ValueError):
            DelegationInstruction(agent_key=" ", task_brief="do it")
        with self.assertRaises(ValueError):
            DelegationInstruction(agent_key="agent", task_brief=" ")
        with self.assertRaises(TypeError):
            DelegationInstruction(
                agent_key="agent",
                task_brief="do it",
                artifacts=("bad",),
            )
        with self.assertRaises(TypeError):
            DelegationInstruction(
                agent_key="agent",
                task_brief="do it",
                metadata="bad",
            )
        with self.assertRaises(TypeError):
            JoinState(policy="bad")
        with self.assertRaises(TypeError):
            JoinState(timeout_at="bad")
        with self.assertRaises(TypeError):
            JoinState(metadata="bad")
        with self.assertRaises(TypeError):
            JoinPolicy(metadata="bad")

        with self.assertRaises(TypeError):
            CapabilityDescriptor(
                key="cap.one",
                title="Title",
                input_schema="bad",
            )
        with self.assertRaises(TypeError):
            CapabilityDescriptor(
                key="cap.one",
                title="Title",
                metadata="bad",
            )

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
        with self.assertRaises(TypeError):
            EvaluationRequest(request=valid_request, run=valid_run, metadata="bad")
        with self.assertRaises(TypeError):
            EvaluationResult(status="pass", scores="bad")
        with self.assertRaises(TypeError):
            EvaluationResult(status="pass", metadata="bad")
        with self.assertRaises(TypeError):
            PlanOutcome(status="completed", metadata="bad")

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
        with self.assertRaises(TypeError):
            PlanDecision(
                kind="respond",
                capability_invocations=("bad",),
            )
        with self.assertRaises(TypeError):
            PlanDecision(
                kind="delegate",
                delegations=("bad",),
            )
        with self.assertRaises(TypeError):
            PlanDecision(
                kind="delegate",
                join_policy="bad",
            )
        with self.assertRaises(TypeError):
            PlanDecision(
                kind="spawn_background",
                background_payload="bad",
            )
        with self.assertRaises(TypeError):
            PlanDecision(
                kind="respond",
                metadata="bad",
            )
        with self.assertRaises(TypeError):
            PreparedPlanRun(
                run_id="run-1",
                mode="current_turn",
                status="prepared",
                state=PlanRunState(goal="hello"),
                policy=AgentRuntimePolicy(),
                request_snapshot={},
                cursor=PlanRunCursor(run_id="run-1"),
                lineage="bad",
            )
        with self.assertRaises(TypeError):
            PreparedPlanRun(
                run_id="run-1",
                mode="current_turn",
                status="prepared",
                state=PlanRunState(goal="hello"),
                policy=AgentRuntimePolicy(),
                request_snapshot={},
                cursor=PlanRunCursor(run_id="run-1"),
                join_state="bad",
            )
        with self.assertRaises(TypeError):
            PreparedPlanRun(
                run_id="run-1",
                mode="current_turn",
                status="prepared",
                state=PlanRunState(goal="hello"),
                policy=AgentRuntimePolicy(),
                request_snapshot={},
                cursor=PlanRunCursor(run_id="run-1"),
                metadata="bad",
            )


if __name__ == "__main__":
    unittest.main()
