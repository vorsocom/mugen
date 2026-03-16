"""Unit tests for ops_vpn vendor lifecycle actions."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.ops_vpn.domain import VendorDE
from mugen.core.plugin.ops_vpn.service.vendor import VendorService


class TestOpsVpnVendorLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests lifecycle transition actions on VendorService."""

    async def test_activate_candidate_sets_status_and_onboarding(self) -> None:
        """Activating a candidate vendor updates status and onboarding timestamp."""
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        svc = VendorService(table="ops_vpn_vendor", rsg=Mock())

        current = VendorDE(
            id=vendor_id,
            tenant_id=tenant_id,
            status="candidate",
            row_version=5,
            onboarding_completed_at=None,
        )
        updated = VendorDE(
            id=vendor_id,
            tenant_id=tenant_id,
            status="active",
            row_version=6,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=updated)

        resp = await svc.action_activate(
            tenant_id=tenant_id,
            entity_id=vendor_id,
            where={"tenant_id": tenant_id, "id": vendor_id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=5),
        )

        self.assertEqual(resp, ("", 204))
        svc.update_with_row_version.assert_awaited_once()
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "active")
        self.assertIsNotNone(changes["onboarding_completed_at"])

    async def test_suspend_requires_active_state(self) -> None:
        """Suspending a non-active vendor should raise a conflict."""
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        svc = VendorService(table="ops_vpn_vendor", rsg=Mock())

        svc.get = AsyncMock(
            side_effect=[
                VendorDE(
                    id=vendor_id,
                    tenant_id=tenant_id,
                    status="candidate",
                    row_version=2,
                )
            ]
        )
        svc.update_with_row_version = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_suspend(
                tenant_id=tenant_id,
                entity_id=vendor_id,
                where={"tenant_id": tenant_id, "id": vendor_id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=2),
            )

        self.assertEqual(ctx.exception.code, 409)
        svc.update_with_row_version.assert_not_called()

    async def test_reverify_updates_due_date(self) -> None:
        """Reverification updates last/next reverification timestamps."""
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        svc = VendorService(table="ops_vpn_vendor", rsg=Mock())

        current = VendorDE(
            id=vendor_id,
            tenant_id=tenant_id,
            status="active",
            row_version=10,
            reverification_cadence_days=30,
            last_reverified_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        updated = VendorDE(
            id=vendor_id,
            tenant_id=tenant_id,
            status="active",
            row_version=11,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=updated)

        resp = await svc.action_reverify(
            tenant_id=tenant_id,
            entity_id=vendor_id,
            where={"tenant_id": tenant_id, "id": vendor_id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=10),
        )

        self.assertEqual(resp, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertIsNotNone(changes["last_reverified_at"])
        self.assertIsNotNone(changes["next_reverification_due_at"])
        self.assertGreater(
            changes["next_reverification_due_at"],
            changes["last_reverified_at"],
        )
