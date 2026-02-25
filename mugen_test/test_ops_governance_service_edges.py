"""Unit tests for ops_governance service edge branches."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_governance.api.validation import (
    ActivatePolicyVersionActionValidation,
    ApplyRetentionActionValidation,
    EvaluatePolicyActionValidation,
    RevokeDelegationActionValidation,
    WithdrawConsentActionValidation,
)
from mugen.core.plugin.ops_governance.domain import (
    ConsentRecordDE,
    DelegationGrantDE,
    PolicyDecisionLogDE,
    PolicyDefinitionDE,
    RetentionPolicyDE,
)
from mugen.core.plugin.ops_governance.service.consent_record import ConsentRecordService
from mugen.core.plugin.ops_governance.service.delegation_grant import (
    DelegationGrantService,
)
from mugen.core.plugin.ops_governance.service.policy_definition import (
    PolicyDefinitionService,
)
from mugen.core.plugin.ops_governance.service.retention_policy import (
    RetentionPolicyService,
)


class TestOpsGovernanceServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Covers helper and inactive/invalid-state guard branches."""

    def test_now_utc_and_normalize_helpers(self) -> None:
        self.assertIsNotNone(PolicyDefinitionService._now_utc().tzinfo)
        self.assertIsNotNone(RetentionPolicyService._now_utc().tzinfo)
        self.assertIsNotNone(ConsentRecordService._now_utc().tzinfo)
        self.assertIsNotNone(DelegationGrantService._now_utc().tzinfo)
        self.assertIsNone(PolicyDefinitionService._normalize_optional_text(None))
        self.assertIsNone(RetentionPolicyService._normalize_optional_text(None))
        self.assertIsNone(ConsentRecordService._normalize_optional_text(None))
        self.assertIsNone(DelegationGrantService._normalize_optional_text(None))

    async def test_policy_get_for_action_raises_500_404_409(self) -> None:
        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition", rsg=Mock()
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[
                None,
                PolicyDefinitionDE(id=where["id"], tenant_id=where["tenant_id"]),
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 409)

    async def test_policy_get_for_action_raises_500_on_base_lookup_sql_error(
        self,
    ) -> None:
        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition", rsg=Mock()
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 500)

    async def test_policy_update_with_row_version_raises_409_500_404(self) -> None:
        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition", rsg=Mock()
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_governance_policy_definition")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"name": "new"},
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"name": "new"},
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"name": "new"},
            )
        self.assertEqual(ctx.exception.code, 404)

    async def test_policy_action_rejects_inactive_policy(self) -> None:
        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition", rsg=Mock()
        )
        tenant_id = uuid.uuid4()
        policy_id = uuid.uuid4()

        svc.get = AsyncMock(
            return_value=PolicyDefinitionDE(
                id=policy_id,
                tenant_id=tenant_id,
                is_active=False,
                row_version=3,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_evaluate_policy(
                tenant_id=tenant_id,
                entity_id=policy_id,
                where={"tenant_id": tenant_id, "id": policy_id},
                auth_user_id=uuid.uuid4(),
                data=EvaluatePolicyActionValidation(
                    row_version=3,
                    subject_namespace="ops.case",
                    subject_ref="CASE-1",
                    decision="allow",
                    outcome="applied",
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

    def test_policy_definition_helper_branches(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            PolicyDefinitionService._normalize_required_text(
                " ",
                field_name="Decision",
            )
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(HTTPException) as ctx:
            PolicyDefinitionService._normalize_decision("invalid")
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(HTTPException) as ctx:
            PolicyDefinitionService._normalize_outcome("invalid")
        self.assertEqual(ctx.exception.code, 400)

        self.assertEqual(
            PolicyDefinitionService._as_mapping(None, field_name="InputJson"),
            {},
        )
        with self.assertRaises(HTTPException) as ctx:
            PolicyDefinitionService._as_mapping("bad", field_name="InputJson")
        self.assertEqual(ctx.exception.code, 409)

        payload = {"ClockId": "C-1", "Nested": {"Value": 3}}
        self.assertEqual(PolicyDefinitionService._event_get(payload, "ClockId"), "C-1")
        self.assertEqual(PolicyDefinitionService._event_get(payload, "clockid"), "C-1")
        self.assertIsNone(PolicyDefinitionService._event_get(payload, "missing"))
        self.assertEqual(
            PolicyDefinitionService._extract_path(payload, "Nested.Value"),
            3,
        )
        self.assertIsNone(PolicyDefinitionService._extract_path(payload, "Nested..Bad"))
        self.assertIsNone(
            PolicyDefinitionService._extract_path({"Nested": "bad"}, "Nested.Value")
        )
        self.assertIsNone(
            PolicyDefinitionService._extract_path(payload, "Nested.Missing")
        )

        self.assertTrue(PolicyDefinitionService._compare("ne", 1, 2))
        self.assertFalse(PolicyDefinitionService._compare("in", "x", "abc"))
        self.assertTrue(PolicyDefinitionService._compare("in", "x", ["x", "y"]))
        self.assertTrue(PolicyDefinitionService._compare("contains", "warned", "arn"))
        self.assertTrue(PolicyDefinitionService._compare("contains", ["a"], "a"))
        self.assertFalse(PolicyDefinitionService._compare("contains", 1, "a"))

        event = {"EventType": "warned", "remaining": 30}
        self.assertFalse(PolicyDefinitionService._matches_condition(event, "bad"))
        self.assertTrue(
            PolicyDefinitionService._matches_condition(
                event,
                {
                    "Any": [
                        {"Path": "remaining", "Op": "eq", "Value": 10},
                        {"EventType": "warned"},
                    ]
                },
            )
        )
        self.assertTrue(
            PolicyDefinitionService._matches_condition(
                event,
                {
                    "All": [
                        {"Path": "remaining", "Op": "ne", "Value": 10},
                        {"EventType": "warned"},
                    ]
                },
            )
        )
        self.assertFalse(
            PolicyDefinitionService._matches_condition(
                event,
                {"EventType": "blocked"},
            )
        )
        self.assertTrue(
            PolicyDefinitionService._matches_condition(
                event,
                {
                    "Path": " ",
                    "Op": "eq",
                    "Value": "ignored",
                    "EventType": "warned",
                },
            )
        )

        reasons = PolicyDefinitionService._rule_reasons(
            {
                "Reason": "primary",
                "Reasons": ["primary", "secondary", 1, " "],
            }
        )
        self.assertEqual(reasons, ["primary", "secondary"])
        self.assertEqual(PolicyDefinitionService._rule_obligations({}), [])
        obligations = PolicyDefinitionService._rule_obligations(
            {"Obligations": [{"Type": "notify"}, "raw"]}
        )
        self.assertEqual(obligations, [{"Type": "notify"}, "raw"])

        self.assertEqual(
            PolicyDefinitionService._rule_decision("allow"),
            "allow",
        )
        self.assertEqual(
            PolicyDefinitionService._rule_decision(None, fallback="deny"),
            "deny",
        )
        with self.assertRaises(ValueError):
            PolicyDefinitionService._rule_decision(None)
        with self.assertRaises(ValueError):
            PolicyDefinitionService._rule_decision("invalid")

        decision_from_when = PolicyDefinitionService._evaluate_document(
            document={
                "Rules": [
                    "bad",
                    {
                        "When": {"Path": "risk", "Op": "eq", "Value": "low"},
                        "Effect": "allow",
                    },
                    {
                        "Match": {"Path": "risk", "Op": "eq", "Value": "high"},
                        "Effect": "review",
                    },
                ]
            },
            input_json={"risk": "high"},
        )
        self.assertEqual(decision_from_when["decision"], "review")

        decision_from_default_scalar = PolicyDefinitionService._evaluate_document(
            document={
                "Rules": [
                    {
                        "Condition": {"Path": "risk", "Op": "eq", "Value": "low"},
                        "Effect": "allow",
                    }
                ],
                "Default": "warn",
            },
            input_json={"risk": "unknown"},
        )
        self.assertEqual(decision_from_default_scalar["decision"], "warn")

        decision_from_default_mapping = PolicyDefinitionService._evaluate_document(
            document={
                "Rules": [],
                "Default": {
                    "Decision": "allow",
                    "Reasons": ["from-default"],
                    "Obligations": [{"Type": "notify"}],
                },
            },
            input_json={"risk": "unknown"},
        )
        self.assertEqual(decision_from_default_mapping["decision"], "allow")
        self.assertEqual(
            decision_from_default_mapping["reasons"],
            ["from-default"],
        )

    async def test_policy_action_evaluate_error_branches(self) -> None:
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
            code="policy",
            version=1,
            is_active=True,
            row_version=3,
            document_json={"Default": "allow"},
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

        response, status = await svc.action_evaluate_policy(
            tenant_id=tenant_id,
            entity_id=policy_id,
            where={"tenant_id": tenant_id, "id": policy_id},
            auth_user_id=actor_id,
            data=EvaluatePolicyActionValidation(
                row_version=3,
                subject_namespace="ops.case",
                subject_ref="CASE-1",
                decision="allow",
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["Reasons"], [])

        missing_input = EvaluatePolicyActionValidation.model_construct(
            row_version=3,
            subject_namespace="ops.case",
            subject_ref="CASE-1",
            decision=None,
            input_json=None,
            outcome=None,
            reason=None,
            trace_id=None,
            request_context=None,
            attributes=None,
            actor_json=None,
            subject_id=None,
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_evaluate_policy(
                tenant_id=tenant_id,
                entity_id=policy_id,
                where={"tenant_id": tenant_id, "id": policy_id},
                auth_user_id=actor_id,
                data=missing_input,
            )
        self.assertEqual(ctx.exception.code, 400)

        invalid_document = PolicyDefinitionDE(
            id=policy_id,
            tenant_id=tenant_id,
            code="policy",
            version=1,
            is_active=True,
            row_version=4,
            document_json={"Rules": [{"Effect": "not-valid"}]},
        )
        svc.get = AsyncMock(return_value=invalid_document)
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_evaluate_policy(
                tenant_id=tenant_id,
                entity_id=policy_id,
                where={"tenant_id": tenant_id, "id": policy_id},
                auth_user_id=actor_id,
                data=EvaluatePolicyActionValidation(
                    row_version=4,
                    subject_namespace="ops.case",
                    subject_ref="CASE-2",
                    input_json={"risk": "high"},
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_activate_version_additional_edge_branches(self) -> None:
        tenant_id = uuid.uuid4()
        anchor_id = uuid.uuid4()
        target_id = uuid.uuid4()
        svc = PolicyDefinitionService(
            table="ops_governance_policy_definition",
            rsg=Mock(),
        )

        svc.get = AsyncMock(
            return_value=PolicyDefinitionDE(
                id=anchor_id,
                tenant_id=tenant_id,
                code=None,
                version=1,
                is_active=True,
                row_version=2,
            )
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_activate_version(
                tenant_id=tenant_id,
                entity_id=anchor_id,
                where={"tenant_id": tenant_id, "id": anchor_id},
                auth_user_id=uuid.uuid4(),
                data=ActivatePolicyVersionActionValidation(row_version=2, version=1),
            )
        self.assertEqual(ctx.exception.code, 409)

        anchor = PolicyDefinitionDE(
            id=anchor_id,
            tenant_id=tenant_id,
            code="policy",
            version=1,
            is_active=True,
            row_version=2,
        )
        svc.get = AsyncMock(return_value=anchor)
        svc.list = AsyncMock(
            side_effect=[
                [
                    PolicyDefinitionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        code="policy",
                        version=2,
                    ),
                    PolicyDefinitionDE(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        code="policy",
                        version=2,
                    ),
                ]
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_activate_version(
                tenant_id=tenant_id,
                entity_id=anchor_id,
                where={"tenant_id": tenant_id, "id": anchor_id},
                auth_user_id=uuid.uuid4(),
                data=ActivatePolicyVersionActionValidation(row_version=2, version=2),
            )
        self.assertEqual(ctx.exception.code, 409)

        target_missing_id = PolicyDefinitionDE(
            id=None,
            tenant_id=tenant_id,
            code="policy",
            version=2,
            is_active=True,
            row_version=3,
        )
        svc.list = AsyncMock(side_effect=[[target_missing_id]])
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_activate_version(
                tenant_id=tenant_id,
                entity_id=anchor_id,
                where={"tenant_id": tenant_id, "id": anchor_id},
                auth_user_id=uuid.uuid4(),
                data=ActivatePolicyVersionActionValidation(row_version=2, version=2),
            )
        self.assertEqual(ctx.exception.code, 409)

        target_active = PolicyDefinitionDE(
            id=target_id,
            tenant_id=tenant_id,
            code="policy",
            version=2,
            is_active=True,
            row_version=5,
        )
        sibling_no_id = PolicyDefinitionDE(
            id=None,
            tenant_id=tenant_id,
            code="policy",
            version=3,
            is_active=True,
            row_version=1,
        )
        sibling_inactive = PolicyDefinitionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            code="policy",
            version=4,
            is_active=False,
            row_version=1,
        )
        svc.list = AsyncMock(
            side_effect=[
                [target_active],
                [target_active, sibling_no_id, sibling_inactive],
            ]
        )
        svc.update_with_row_version = AsyncMock()
        response, status = await svc.action_activate_version(
            tenant_id=tenant_id,
            entity_id=anchor_id,
            where={"tenant_id": tenant_id, "id": anchor_id},
            auth_user_id=uuid.uuid4(),
            data=ActivatePolicyVersionActionValidation(row_version=2, version=2),
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["PolicyId"], str(target_id))
        svc.update_with_row_version.assert_not_awaited()

        sibling_bad_row_version = PolicyDefinitionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            code="policy",
            version=3,
            is_active=True,
            row_version=0,
        )
        svc.list = AsyncMock(
            side_effect=[
                [target_active],
                [target_active, sibling_bad_row_version],
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_activate_version(
                tenant_id=tenant_id,
                entity_id=anchor_id,
                where={"tenant_id": tenant_id, "id": anchor_id},
                auth_user_id=uuid.uuid4(),
                data=ActivatePolicyVersionActionValidation(row_version=2, version=2),
            )
        self.assertEqual(ctx.exception.code, 409)

        target_inactive_bad_rv = PolicyDefinitionDE(
            id=target_id,
            tenant_id=tenant_id,
            code="policy",
            version=2,
            is_active=False,
            row_version=0,
        )
        svc.list = AsyncMock(
            side_effect=[
                [target_inactive_bad_rv],
                [target_inactive_bad_rv],
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_activate_version(
                tenant_id=tenant_id,
                entity_id=anchor_id,
                where={"tenant_id": tenant_id, "id": anchor_id},
                auth_user_id=uuid.uuid4(),
                data=ActivatePolicyVersionActionValidation(row_version=2, version=2),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_retention_get_for_action_raises_500_404_409(self) -> None:
        svc = RetentionPolicyService(
            table="ops_governance_retention_policy", rsg=Mock()
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[
                None,
                RetentionPolicyDE(id=where["id"], tenant_id=where["tenant_id"]),
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 409)

    async def test_retention_get_for_action_raises_500_on_base_lookup_sql_error(
        self,
    ) -> None:
        svc = RetentionPolicyService(
            table="ops_governance_retention_policy", rsg=Mock()
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 500)

    async def test_retention_update_with_row_version_raises_409_500_404(self) -> None:
        svc = RetentionPolicyService(
            table="ops_governance_retention_policy", rsg=Mock()
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_governance_retention_policy")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"name": "new"},
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"name": "new"},
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"name": "new"},
            )
        self.assertEqual(ctx.exception.code, 404)

    async def test_retention_action_rejects_inactive_policy(self) -> None:
        svc = RetentionPolicyService(
            table="ops_governance_retention_policy", rsg=Mock()
        )
        tenant_id = uuid.uuid4()
        policy_id = uuid.uuid4()

        svc.get = AsyncMock(
            return_value=RetentionPolicyDE(
                id=policy_id,
                tenant_id=tenant_id,
                is_active=False,
                row_version=2,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_apply_retention_action(
                tenant_id=tenant_id,
                entity_id=policy_id,
                where={"tenant_id": tenant_id, "id": policy_id},
                auth_user_id=uuid.uuid4(),
                data=ApplyRetentionActionValidation(
                    row_version=2,
                    action_type="redaction",
                    subject_namespace="ops.case_event",
                    subject_ref="EVT-1",
                    request_status="pending",
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_consent_get_for_action_raises_500_404_409(self) -> None:
        svc = ConsentRecordService(table="ops_governance_consent_record", rsg=Mock())
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[
                None,
                ConsentRecordDE(id=where["id"], tenant_id=where["tenant_id"]),
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 409)

    async def test_consent_get_for_action_raises_500_on_base_lookup_sql_error(
        self,
    ) -> None:
        svc = ConsentRecordService(table="ops_governance_consent_record", rsg=Mock())
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 500)

    async def test_withdraw_consent_rejects_non_granted_status(self) -> None:
        svc = ConsentRecordService(table="ops_governance_consent_record", rsg=Mock())
        tenant_id = uuid.uuid4()
        consent_id = uuid.uuid4()
        svc.get = AsyncMock(
            return_value=ConsentRecordDE(
                id=consent_id,
                tenant_id=tenant_id,
                status="withdrawn",
                row_version=4,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_withdraw_consent(
                tenant_id=tenant_id,
                entity_id=consent_id,
                where={"tenant_id": tenant_id, "id": consent_id},
                auth_user_id=uuid.uuid4(),
                data=WithdrawConsentActionValidation(row_version=4),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_delegation_get_for_action_raises_500_404_409(self) -> None:
        svc = DelegationGrantService(
            table="ops_governance_delegation_grant", rsg=Mock()
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[
                None,
                DelegationGrantDE(id=where["id"], tenant_id=where["tenant_id"]),
            ]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 409)

    async def test_delegation_get_for_action_raises_500_on_base_lookup_sql_error(
        self,
    ) -> None:
        svc = DelegationGrantService(
            table="ops_governance_delegation_grant", rsg=Mock()
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(ctx.exception.code, 500)

    async def test_revoke_delegation_rejects_non_active_status(self) -> None:
        svc = DelegationGrantService(
            table="ops_governance_delegation_grant", rsg=Mock()
        )
        tenant_id = uuid.uuid4()
        grant_id = uuid.uuid4()
        svc.get = AsyncMock(
            return_value=DelegationGrantDE(
                id=grant_id,
                tenant_id=tenant_id,
                status="revoked",
                row_version=5,
                effective_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_revoke_delegation(
                tenant_id=tenant_id,
                entity_id=grant_id,
                where={"tenant_id": tenant_id, "id": grant_id},
                auth_user_id=uuid.uuid4(),
                data=RevokeDelegationActionValidation(row_version=5),
            )
        self.assertEqual(ctx.exception.code, 409)
