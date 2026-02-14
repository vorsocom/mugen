"""Unit tests for ops_governance service edge branches."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_governance.api.validation import (
    ApplyRetentionActionValidation,
    EvaluatePolicyActionValidation,
    RevokeDelegationActionValidation,
    WithdrawConsentActionValidation,
)
from mugen.core.plugin.ops_governance.domain import (
    ConsentRecordDE,
    DelegationGrantDE,
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
