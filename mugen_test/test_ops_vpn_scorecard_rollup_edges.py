"""Edge-case unit tests for ops_vpn vendor scorecard rollup service."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.plugin.ops_vpn.domain import VendorScorecardDE
from mugen.core.plugin.ops_vpn.service import vendor_scorecard as vendor_scorecard_mod
from mugen.core.plugin.ops_vpn.service.vendor_scorecard import VendorScorecardService


class TestOpsVpnScorecardRollupEdges(unittest.IsolatedAsyncioTestCase):
    """Branch-focused tests for VendorScorecardService edge behavior."""

    def _service(self) -> VendorScorecardService:
        rsg = Mock()
        rsg.find_many = AsyncMock(return_value=[])
        rsg.get_one = AsyncMock(return_value=None)
        svc = VendorScorecardService(table="ops_vpn_vendor_scorecard", rsg=rsg)
        svc.get = AsyncMock(return_value=None)
        svc.create = AsyncMock()
        svc.update = AsyncMock()
        return svc

    def test_helper_methods_cover_none_and_unknown_paths(self) -> None:
        self.assertIsNone(VendorScorecardService._safe_score(None))
        self.assertEqual(VendorScorecardService._tokenize_enum_value(None), "")
        self.assertIsNone(
            VendorScorecardService._normalized_event_score(
                "unsupported_metric",
                {"metric_numerator": 1, "metric_denominator": 2},
            )
        )

    async def test_rollup_period_aborts_on_invalid_period_range(self) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        period_start = datetime.now(timezone.utc)
        period_end = period_start - timedelta(seconds=1)

        with (
            patch.object(
                vendor_scorecard_mod,
                "abort",
                side_effect=lambda code, message: (_ for _ in ()).throw(
                    RuntimeError(f"{code}:{message}")
                ),
            ) as abort_mock,
            self.assertRaises(RuntimeError),
        ):
            await svc.rollup_period(
                tenant_id=tenant_id,
                vendor_id=vendor_id,
                period_start=period_start,
                period_end=period_end,
            )

        abort_mock.assert_called_once_with(
            400,
            "PeriodEnd must be greater than or equal to PeriodStart.",
        )

    async def test_rollup_period_handles_unknown_metric_and_zero_weights(self) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=1)
        period_end = now

        svc._rsg.find_many = AsyncMock(
            return_value=[
                {
                    "metric_type": "unsupported_metric",
                    "normalized_score": 77,
                    "sample_size": 1,
                },
                {
                    "metric_type": "completion_rate",
                    "normalized_score": 80,
                    "sample_size": 1,
                },
            ]
        )

        async def _get_one(table, where, columns=None):  # noqa: ANN001, ANN202
            if table == "ops_vpn_vendor":
                return {
                    "status": "active",
                    "next_reverification_due_at": now + timedelta(days=30),
                }
            if table == "ops_vpn_scorecard_policy":
                return {
                    "time_to_quote_weight": 0,
                    "completion_rate_weight": 0,
                    "complaint_rate_weight": 0,
                    "response_sla_weight": 0,
                    "min_sample_size": 1,
                    "minimum_overall_score": 0,
                    "require_all_metrics": False,
                }
            return None

        svc._rsg.get_one = AsyncMock(side_effect=_get_one)

        created = VendorScorecardDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
            completion_rate_score=80,
            overall_score=None,
            is_routable=False,
        )
        svc.create = AsyncMock(return_value=created)

        result = await svc.rollup_period(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
        )

        self.assertIsNone(result.overall_score)
        payload = svc.create.await_args.args[0]
        self.assertEqual(payload["event_count"], 2)
        self.assertEqual(payload["completion_rate_score"], 80)
        self.assertIsNone(payload["overall_score"])

    async def test_rollup_period_aborts_when_vendor_missing(self) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=1)
        period_end = now

        svc._rsg.find_many = AsyncMock(return_value=[])
        svc._rsg.get_one = AsyncMock(return_value=None)

        with (
            patch.object(
                vendor_scorecard_mod,
                "abort",
                side_effect=lambda code, message: (_ for _ in ()).throw(
                    RuntimeError(f"{code}:{message}")
                ),
            ) as abort_mock,
            self.assertRaises(RuntimeError),
        ):
            await svc.rollup_period(
                tenant_id=tenant_id,
                vendor_id=vendor_id,
                period_start=period_start,
                period_end=period_end,
            )

        abort_mock.assert_called_once_with(404, "Vendor not found.")

    async def test_rollup_period_aborts_when_update_returns_none(self) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=1)
        period_end = now

        async def _get_one(table, where, columns=None):  # noqa: ANN001, ANN202
            if table == "ops_vpn_vendor":
                return {
                    "status": "active",
                    "next_reverification_due_at": now + timedelta(days=30),
                }
            if table == "ops_vpn_scorecard_policy":
                return None
            return None

        svc._rsg.find_many = AsyncMock(return_value=[])
        svc._rsg.get_one = AsyncMock(side_effect=_get_one)
        svc.get = AsyncMock(return_value=VendorScorecardDE(id=uuid.uuid4()))
        svc.update = AsyncMock(return_value=None)

        with (
            patch.object(
                vendor_scorecard_mod,
                "abort",
                side_effect=lambda code, message: (_ for _ in ()).throw(
                    RuntimeError(f"{code}:{message}")
                ),
            ) as abort_mock,
            self.assertRaises(RuntimeError),
        ):
            await svc.rollup_period(
                tenant_id=tenant_id,
                vendor_id=vendor_id,
                period_start=period_start,
                period_end=period_end,
            )

        abort_mock.assert_called_once_with(
            404,
            "Scorecard update not performed. No row matched.",
        )

    async def test_rollup_period_returns_updated_scorecard_when_update_succeeds(
        self,
    ) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=1)
        period_end = now

        async def _get_one(table, where, columns=None):  # noqa: ANN001, ANN202
            if table == "ops_vpn_vendor":
                return {
                    "status": "active",
                    "next_reverification_due_at": now + timedelta(days=30),
                }
            if table == "ops_vpn_scorecard_policy":
                return None
            return None

        updated = VendorScorecardDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
            overall_score=None,
            is_routable=False,
        )
        svc._rsg.find_many = AsyncMock(return_value=[])
        svc._rsg.get_one = AsyncMock(side_effect=_get_one)
        svc.get = AsyncMock(return_value=VendorScorecardDE(id=uuid.uuid4()))
        svc.update = AsyncMock(return_value=updated)

        result = await svc.rollup_period(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
        )

        self.assertIs(result, updated)
        svc.update.assert_awaited_once()

    async def test_action_rollup_serializes_scorecard_payload(self) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        period_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        period_end = datetime(2026, 1, 31, tzinfo=timezone.utc)
        scorecard = VendorScorecardDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
            overall_score=88,
            is_routable=True,
        )
        svc.rollup_period = AsyncMock(return_value=scorecard)

        result = await svc.action_rollup(
            tenant_id=tenant_id,
            where={},
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                vendor_id=vendor_id,
                period_start=period_start,
                period_end=period_end,
            ),
        )

        self.assertEqual(result["Id"], str(scorecard.id))
        self.assertEqual(result["VendorId"], str(vendor_id))
        self.assertEqual(result["PeriodStart"], period_start.isoformat())
        self.assertEqual(result["PeriodEnd"], period_end.isoformat())
        self.assertEqual(result["OverallScore"], 88)
        self.assertTrue(result["IsRoutable"])
