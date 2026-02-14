"""Unit tests for ops_governance consent/delegation lifecycle behavior."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.ops_governance.api.validation import (
    GrantDelegationActionValidation,
    RecordConsentActionValidation,
    RevokeDelegationActionValidation,
    WithdrawConsentActionValidation,
)
from mugen.core.plugin.ops_governance.domain import ConsentRecordDE, DelegationGrantDE
from mugen.core.plugin.ops_governance.service.consent_record import ConsentRecordService
from mugen.core.plugin.ops_governance.service.delegation_grant import (
    DelegationGrantService,
)


class TestOpsGovernanceLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests append-only consent and delegation lifecycle actions."""

    async def test_record_then_withdraw_consent_appends_history(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        consent_id = uuid.uuid4()
        subject_user_id = uuid.uuid4()
        now = datetime(2026, 2, 13, 19, 20, tzinfo=timezone.utc)

        svc = ConsentRecordService(table="ops_governance_consent_record", rsg=Mock())
        svc._now_utc = lambda: now

        granted = ConsentRecordDE(
            id=consent_id,
            tenant_id=tenant_id,
            subject_user_id=subject_user_id,
            controller_namespace="ops.case",
            purpose="triage",
            scope="read:case",
            status="granted",
            row_version=3,
        )

        svc.create = AsyncMock(return_value=granted)

        create_resp = await svc.action_record_consent(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=RecordConsentActionValidation(
                subject_user_id=subject_user_id,
                controller_namespace="ops.case",
                purpose="triage",
                scope="read:case",
            ),
        )

        self.assertEqual(create_resp[1], 201)
        create_payload = svc.create.await_args.args[0]
        self.assertEqual(create_payload["status"], "granted")

        withdrawn = ConsentRecordDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            subject_user_id=subject_user_id,
            controller_namespace="ops.case",
            purpose="triage",
            scope="read:case",
            status="withdrawn",
            row_version=1,
        )

        svc.get = AsyncMock(return_value=granted)
        svc.create = AsyncMock(return_value=withdrawn)

        withdraw_resp = await svc.action_withdraw_consent(
            tenant_id=tenant_id,
            entity_id=consent_id,
            where={"tenant_id": tenant_id, "id": consent_id},
            auth_user_id=actor_id,
            data=WithdrawConsentActionValidation(
                row_version=3,
                reason="user request",
            ),
        )

        self.assertEqual(withdraw_resp[1], 201)
        withdraw_payload = svc.create.await_args.args[0]
        self.assertEqual(withdraw_payload["status"], "withdrawn")
        self.assertEqual(withdraw_payload["source_consent_id"], consent_id)
        self.assertEqual(withdraw_payload["withdrawn_by_user_id"], actor_id)
        self.assertEqual(withdraw_payload["withdrawal_reason"], "user request")

    async def test_grant_then_revoke_delegation_appends_history(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        grant_id = uuid.uuid4()
        principal_user_id = uuid.uuid4()
        delegate_user_id = uuid.uuid4()
        now = datetime(2026, 2, 13, 19, 25, tzinfo=timezone.utc)

        svc = DelegationGrantService(
            table="ops_governance_delegation_grant",
            rsg=Mock(),
        )
        svc._now_utc = lambda: now

        active = DelegationGrantDE(
            id=grant_id,
            tenant_id=tenant_id,
            principal_user_id=principal_user_id,
            delegate_user_id=delegate_user_id,
            scope="manage:case",
            status="active",
            row_version=4,
        )

        svc.create = AsyncMock(return_value=active)

        create_resp = await svc.action_grant_delegation(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=GrantDelegationActionValidation(
                principal_user_id=principal_user_id,
                delegate_user_id=delegate_user_id,
                scope="manage:case",
            ),
        )

        self.assertEqual(create_resp[1], 201)
        create_payload = svc.create.await_args.args[0]
        self.assertEqual(create_payload["status"], "active")

        revoked = DelegationGrantDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            principal_user_id=principal_user_id,
            delegate_user_id=delegate_user_id,
            scope="manage:case",
            status="revoked",
            row_version=1,
        )

        svc.get = AsyncMock(return_value=active)
        svc.create = AsyncMock(return_value=revoked)

        revoke_resp = await svc.action_revoke_delegation(
            tenant_id=tenant_id,
            entity_id=grant_id,
            where={"tenant_id": tenant_id, "id": grant_id},
            auth_user_id=actor_id,
            data=RevokeDelegationActionValidation(
                row_version=4,
                reason="policy change",
            ),
        )

        self.assertEqual(revoke_resp[1], 201)
        revoke_payload = svc.create.await_args.args[0]
        self.assertEqual(revoke_payload["status"], "revoked")
        self.assertEqual(revoke_payload["source_grant_id"], grant_id)
        self.assertEqual(revoke_payload["revoked_by_user_id"], actor_id)
        self.assertEqual(revoke_payload["revocation_reason"], "policy change")
