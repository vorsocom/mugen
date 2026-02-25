"""Unit tests for ops_governance policy evaluation and retention metadata actions."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.ops_governance.api.validation import (
    ActivatePolicyVersionActionValidation,
    ApplyRetentionActionValidation,
    EvaluatePolicyActionValidation,
)
from mugen.core.plugin.ops_governance.domain import (
    DataHandlingRecordDE,
    PolicyDecisionLogDE,
    PolicyDefinitionDE,
    RetentionPolicyDE,
)
from mugen.core.plugin.ops_governance.service.policy_definition import (
    PolicyDefinitionService,
)
from mugen.core.plugin.ops_governance.service.retention_policy import (
    RetentionPolicyService,
)
from werkzeug.exceptions import HTTPException


class TestOpsGovernancePolicyRetention(unittest.IsolatedAsyncioTestCase):
    """Tests policy evaluation logging and retention action metadata."""

    async def test_evaluate_policy_appends_decision_log(self) -> None:
        tenant_id = uuid.uuid4()
        policy_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        now = datetime(2026, 2, 13, 19, 30, tzinfo=timezone.utc)

        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition",
            rsg=Mock(),
        )
        svc._now_utc = lambda: now

        current = PolicyDefinitionDE(
            id=policy_id,
            tenant_id=tenant_id,
            code="case-delegation",
            name="Case Delegation",
            is_active=True,
            row_version=5,
        )

        decision = PolicyDecisionLogDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            policy_definition_id=policy_id,
            decision="allow",
            outcome="applied",
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._decision_log_service.create = AsyncMock(return_value=decision)

        result = await svc.action_evaluate_policy(
            tenant_id=tenant_id,
            entity_id=policy_id,
            where={"tenant_id": tenant_id, "id": policy_id},
            auth_user_id=actor_id,
            data=EvaluatePolicyActionValidation(
                row_version=5,
                subject_namespace="ops.case",
                subject_ref="CASE-123",
                decision="allow",
                outcome="applied",
                reason="delegation valid",
            ),
        )

        self.assertEqual(result[1], 200)
        decision_payload = svc._decision_log_service.create.await_args.args[0]
        self.assertEqual(decision_payload["tenant_id"], tenant_id)
        self.assertEqual(decision_payload["policy_definition_id"], policy_id)
        self.assertEqual(decision_payload["decision"], "allow")

        update_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(update_changes["last_decision_log_id"], decision.id)
        self.assertEqual(update_changes["last_evaluated_by_user_id"], actor_id)

    async def test_apply_retention_action_writes_metadata(self) -> None:
        tenant_id = uuid.uuid4()
        policy_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        subject_id = uuid.uuid4()
        now = datetime(2026, 2, 13, 19, 40, tzinfo=timezone.utc)

        svc = RetentionPolicyService(
            table="ops_governance_retention_policy",
            rsg=Mock(),
        )
        svc._now_utc = lambda: now

        current = RetentionPolicyDE(
            id=policy_id,
            tenant_id=tenant_id,
            code="case-events",
            name="Case Event Retention",
            is_active=True,
            row_version=6,
        )
        record = DataHandlingRecordDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            retention_policy_id=policy_id,
            request_type="redaction",
            request_status="pending",
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._data_handling_service.create = AsyncMock(return_value=record)

        result = await svc.action_apply_retention_action(
            tenant_id=tenant_id,
            entity_id=policy_id,
            where={"tenant_id": tenant_id, "id": policy_id},
            auth_user_id=actor_id,
            data=ApplyRetentionActionValidation(
                row_version=6,
                action_type="redaction",
                subject_namespace="ops.case_event",
                subject_id=subject_id,
                request_status="pending",
                note="queued for downstream processor",
                meta={"request_id": "REQ-1001"},
            ),
        )

        self.assertEqual(result[1], 200)
        handling_payload = svc._data_handling_service.create.await_args.args[0]
        self.assertEqual(handling_payload["retention_policy_id"], policy_id)
        self.assertEqual(handling_payload["request_type"], "redaction")
        self.assertEqual(handling_payload["request_status"], "pending")
        self.assertEqual(handling_payload["subject_id"], subject_id)

        update_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(update_changes["last_action_type"], "redaction")
        self.assertEqual(update_changes["last_action_status"], "pending")
        self.assertEqual(update_changes["last_action_by_user_id"], actor_id)

    async def test_evaluate_policy_pdp_denies_by_default_and_logs_trace(self) -> None:
        tenant_id = uuid.uuid4()
        policy_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition",
            rsg=Mock(),
        )
        current = PolicyDefinitionDE(
            id=policy_id,
            tenant_id=tenant_id,
            code="case-policy",
            version=2,
            is_active=True,
            row_version=9,
            document_json={},
        )
        decision = PolicyDecisionLogDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            policy_definition_id=policy_id,
            decision="deny",
            outcome="blocked",
        )
        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._decision_log_service.create = AsyncMock(return_value=decision)

        response, status = await svc.action_evaluate_policy(
            tenant_id=tenant_id,
            entity_id=policy_id,
            where={"tenant_id": tenant_id, "id": policy_id},
            auth_user_id=actor_id,
            data=EvaluatePolicyActionValidation(
                row_version=9,
                trace_id="trace-01",
                subject_namespace="ops.case",
                subject_ref="CASE-1",
                input_json={"Risk": "unknown"},
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["Decision"], "deny")
        self.assertEqual(response["Outcome"], "blocked")
        self.assertFalse(response["Allow"])
        self.assertEqual(response["TraceId"], "trace-01")
        self.assertEqual(response["PolicyCode"], "case-policy")
        self.assertEqual(response["PolicyVersion"], 2)

        payload = svc._decision_log_service.create.await_args.args[0]
        self.assertEqual(payload["trace_id"], "trace-01")
        self.assertEqual(payload["policy_key"], "case-policy")
        self.assertEqual(payload["policy_version"], 2)
        self.assertEqual(payload["input_json"]["Risk"], "unknown")

    async def test_evaluate_policy_pdp_emits_obligations(self) -> None:
        tenant_id = uuid.uuid4()
        policy_id = uuid.uuid4()

        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition",
            rsg=Mock(),
        )
        current = PolicyDefinitionDE(
            id=policy_id,
            tenant_id=tenant_id,
            code="approval-policy",
            version=5,
            is_active=True,
            row_version=4,
            document_json={
                "Rules": [
                    {
                        "Condition": {"Path": "risk", "Op": "eq", "Value": "high"},
                        "Effect": "review",
                        "Reasons": ["high risk requires review"],
                        "Obligations": [
                            {"Type": "require_approval"},
                            {"Type": "log_reason", "Required": True},
                        ],
                    }
                ]
            },
        )
        decision = PolicyDecisionLogDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            policy_definition_id=policy_id,
            decision="review",
            outcome="deferred",
        )
        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._decision_log_service.create = AsyncMock(return_value=decision)

        response, status = await svc.action_evaluate_policy(
            tenant_id=tenant_id,
            entity_id=policy_id,
            where={"tenant_id": tenant_id, "id": policy_id},
            auth_user_id=uuid.uuid4(),
            data=EvaluatePolicyActionValidation(
                row_version=4,
                subject_namespace="ops.case",
                subject_ref="CASE-9",
                input_json={"risk": "high"},
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["Decision"], "review")
        self.assertEqual(response["Outcome"], "deferred")
        self.assertEqual(len(response["Obligations"]), 2)
        self.assertIn("high risk requires review", response["Reasons"])

    async def test_activate_version_switches_active_policy_version(self) -> None:
        tenant_id = uuid.uuid4()
        anchor_id = uuid.uuid4()
        target_id = uuid.uuid4()

        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition",
            rsg=Mock(),
        )
        anchor = PolicyDefinitionDE(
            id=anchor_id,
            tenant_id=tenant_id,
            code="case-policy",
            version=1,
            is_active=True,
            row_version=3,
        )
        target = PolicyDefinitionDE(
            id=target_id,
            tenant_id=tenant_id,
            code="case-policy",
            version=2,
            is_active=False,
            row_version=8,
        )
        deactivated = PolicyDefinitionDE(
            id=anchor_id,
            tenant_id=tenant_id,
            code="case-policy",
            version=1,
            is_active=False,
            row_version=4,
        )
        activated = PolicyDefinitionDE(
            id=target_id,
            tenant_id=tenant_id,
            code="case-policy",
            version=2,
            is_active=True,
            row_version=9,
        )
        svc.get = AsyncMock(return_value=anchor)
        svc.list = AsyncMock(side_effect=[[target], [anchor, target]])
        svc.update_with_row_version = AsyncMock(side_effect=[deactivated, activated])

        response, status = await svc.action_activate_version(
            tenant_id=tenant_id,
            entity_id=anchor_id,
            where={"tenant_id": tenant_id, "id": anchor_id},
            auth_user_id=uuid.uuid4(),
            data=ActivatePolicyVersionActionValidation(
                row_version=3,
                version=2,
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["PolicyId"], str(target_id))
        self.assertEqual(response["Version"], 2)
        self.assertTrue(response["IsActive"])
        self.assertEqual(svc.update_with_row_version.await_count, 2)

    async def test_activate_version_returns_404_for_missing_target(self) -> None:
        tenant_id = uuid.uuid4()
        anchor_id = uuid.uuid4()
        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition",
            rsg=Mock(),
        )
        svc.get = AsyncMock(
            return_value=PolicyDefinitionDE(
                id=anchor_id,
                tenant_id=tenant_id,
                code="case-policy",
                version=1,
                is_active=True,
                row_version=2,
            )
        )
        svc.list = AsyncMock(return_value=[])

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_activate_version(
                tenant_id=tenant_id,
                entity_id=anchor_id,
                where={"tenant_id": tenant_id, "id": anchor_id},
                auth_user_id=uuid.uuid4(),
                data=ActivatePolicyVersionActionValidation(
                    row_version=2,
                    version=2,
                ),
            )
        self.assertEqual(ctx.exception.code, 404)
