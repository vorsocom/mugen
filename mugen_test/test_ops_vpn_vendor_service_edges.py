"""Unit tests for ops_vpn VendorService edge branches."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.ops_vpn.domain import VendorDE
from mugen.core.plugin.ops_vpn.service.vendor import VendorService


class TestOpsVpnVendorServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Covers helper and guard branches not hit by lifecycle tests."""

    def _svc(self) -> VendorService:
        return VendorService(table="ops_vpn_vendor", rsg=Mock())

    async def test_get_for_action_raises_500_on_sql_error(self) -> None:
        svc = self._svc()
        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where={"id": uuid.uuid4()}, expected_row_version=1
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_get_for_action_raises_404_and_409_for_missing_or_conflict(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": vendor_id}

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=2)
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[None, VendorDE(id=vendor_id, tenant_id=tenant_id)]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=2)
        self.assertEqual(ctx.exception.code, 409)

    async def test_get_for_action_raises_500_on_base_lookup_sql_error(self) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=2)

        self.assertEqual(ctx.exception.code, 500)

    async def test_update_status_raises_for_conflict_sql_and_none(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": vendor_id}
        svc._get_for_action = AsyncMock(
            return_value=VendorDE(id=vendor_id, tenant_id=tenant_id, status="candidate")
        )

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_vpn_vendor")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_status(
                where=where,
                expected_row_version=1,
                from_statuses={"candidate"},
                to_status="active",
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_status(
                where=where,
                expected_row_version=1,
                from_statuses={"candidate"},
                to_status="active",
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_status(
                where=where,
                expected_row_version=1,
                from_statuses={"candidate"},
                to_status="active",
            )
        self.assertEqual(ctx.exception.code, 404)

    async def test_action_activate_preserves_existing_onboarding_timestamp(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        onboarding_completed_at = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
        current = VendorDE(
            id=vendor_id,
            tenant_id=tenant_id,
            status="candidate",
            row_version=3,
            onboarding_completed_at=onboarding_completed_at,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)

        result = await svc.action_activate(
            tenant_id=tenant_id,
            entity_id=vendor_id,
            where={"tenant_id": tenant_id, "id": vendor_id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=3),
        )

        self.assertEqual(result, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["onboarding_completed_at"], onboarding_completed_at)

    async def test_action_delist_delegates_to_update_status(self) -> None:
        svc = self._svc()
        svc._update_status = AsyncMock(return_value=("", 204))
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()

        result = await svc.action_delist(
            tenant_id=tenant_id,
            entity_id=vendor_id,
            where={"tenant_id": tenant_id, "id": vendor_id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=4),
        )

        self.assertEqual(result, ("", 204))
        svc._update_status.assert_awaited_once()

    async def test_action_reverify_rejects_delisted_vendor(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()

        svc.get = AsyncMock(
            return_value=VendorDE(
                id=vendor_id,
                tenant_id=tenant_id,
                status="delisted",
                row_version=5,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_reverify(
                tenant_id=tenant_id,
                entity_id=vendor_id,
                where={"tenant_id": tenant_id, "id": vendor_id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=5),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_action_reverify_defaults_cadence_and_sets_candidate_onboarding(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        current = VendorDE(
            id=vendor_id,
            tenant_id=tenant_id,
            status="candidate",
            row_version=6,
            reverification_cadence_days=-1,
            onboarding_completed_at=None,
        )
        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)

        result = await svc.action_reverify(
            tenant_id=tenant_id,
            entity_id=vendor_id,
            where={"tenant_id": tenant_id, "id": vendor_id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=6),
        )

        self.assertEqual(result, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertIsNotNone(changes["onboarding_completed_at"])
        self.assertEqual(
            int(
                (
                    changes["next_reverification_due_at"]
                    - changes["last_reverified_at"]
                ).days
            ),
            365,
        )

    async def test_action_reverify_raises_for_conflict_sql_and_none(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        current = VendorDE(
            id=vendor_id,
            tenant_id=tenant_id,
            status="active",
            row_version=7,
            reverification_cadence_days=30,
        )

        svc.get = AsyncMock(return_value=current)

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_vpn_vendor")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_reverify(
                tenant_id=tenant_id,
                entity_id=vendor_id,
                where={"tenant_id": tenant_id, "id": vendor_id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=7),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_reverify(
                tenant_id=tenant_id,
                entity_id=vendor_id,
                where={"tenant_id": tenant_id, "id": vendor_id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=7),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_reverify(
                tenant_id=tenant_id,
                entity_id=vendor_id,
                where={"tenant_id": tenant_id, "id": vendor_id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=7),
            )
        self.assertEqual(ctx.exception.code, 404)
