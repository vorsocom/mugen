"""Unit tests for ops_governance policy evaluation and retention metadata actions."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.ops_governance.api.validation import (
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
