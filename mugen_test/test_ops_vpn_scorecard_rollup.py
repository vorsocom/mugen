"""Unit tests for ops_vpn scorecard rollup behavior."""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.ops_vpn.domain import VendorScorecardDE
from mugen.core.plugin.ops_vpn.model.vendor import VendorLifecycleStatus
from mugen.core.plugin.ops_vpn.model.vendor_performance_event import VendorMetricType
from mugen.core.plugin.ops_vpn.service.vendor_scorecard import VendorScorecardService


class TestOpsVpnScorecardRollup(unittest.IsolatedAsyncioTestCase):
    """Tests score rollup calculations and routing flags."""

    async def test_rollup_period_computes_scores_and_routable_flag(self) -> None:
        """Rollup should normalize rates and persist a routable snapshot."""
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=7)
        period_end = now

        rsg = Mock()
        rsg.find_many = AsyncMock(
            return_value=[
                {
                    "metric_type": "completion_rate",
                    "metric_numerator": 90,
                    "metric_denominator": 100,
                },
                {
                    "metric_type": "complaint_rate",
                    "metric_numerator": 5,
                    "metric_denominator": 100,
                },
                {
                    "metric_type": "response_sla_adherence",
                    "normalized_score": 87,
                },
                {
                    "metric_type": "time_to_quote",
                    "metric_value": 2400,
                },
            ]
        )
        async def _get_one(table, where, columns=None):  # noqa: ANN001, ANN202
            if table == "ops_vpn_vendor":
                return {
                    "status": "active",
                    "next_reverification_due_at": now + timedelta(days=10),
                }
            if table == "ops_vpn_scorecard_policy":
                return None
            return None

        rsg.get_one = AsyncMock(side_effect=_get_one)

        svc = VendorScorecardService(table="ops_vpn_vendor_scorecard", rsg=rsg)
        svc.get = AsyncMock(return_value=None)
        created = VendorScorecardDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
            completion_rate_score=90,
            complaint_rate_score=95,
            response_sla_score=87,
            overall_score=91,
            is_routable=True,
        )
        svc.create = AsyncMock(return_value=created)

        result = await svc.rollup_period(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
        )

        self.assertEqual(result.overall_score, 91)
        self.assertTrue(result.is_routable)
        svc.create.assert_awaited_once()

        payload = svc.create.await_args.args[0]
        self.assertEqual(payload["completion_rate_score"], 90)
        self.assertEqual(payload["complaint_rate_score"], 95)
        self.assertEqual(payload["response_sla_score"], 87)
        self.assertIsNone(payload["time_to_quote_score"])
        self.assertEqual(payload["overall_score"], 91)
        self.assertEqual(payload["event_count"], 4)
        self.assertTrue(payload["is_routable"])
        self.assertIn("time_to_quote", payload["status_flags"]["missing_metrics"])
        self.assertEqual(payload["status_flags"]["policy"]["code"], "default")

    async def test_rollup_period_applies_default_policy_thresholds(self) -> None:
        """Routability should honor tenant scorecard policy constraints."""
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=7)
        period_end = now

        rsg = Mock()
        rsg.find_many = AsyncMock(
            return_value=[
                {
                    "metric_type": "completion_rate",
                    "metric_numerator": 90,
                    "metric_denominator": 100,
                    "sample_size": 2,
                },
                {
                    "metric_type": "response_sla_adherence",
                    "normalized_score": 80,
                    "sample_size": 2,
                },
            ]
        )

        async def _get_one(table, where, columns=None):  # noqa: ANN001, ANN202
            if table == "ops_vpn_vendor":
                return {
                    "status": "active",
                    "next_reverification_due_at": now + timedelta(days=10),
                }
            if table == "ops_vpn_scorecard_policy":
                return {
                    "time_to_quote_weight": 25,
                    "completion_rate_weight": 25,
                    "complaint_rate_weight": 25,
                    "response_sla_weight": 25,
                    "min_sample_size": 5,
                    "minimum_overall_score": 85,
                    "require_all_metrics": False,
                }
            return None

        rsg.get_one = AsyncMock(side_effect=_get_one)

        svc = VendorScorecardService(table="ops_vpn_vendor_scorecard", rsg=rsg)
        svc.get = AsyncMock(return_value=None)
        created = VendorScorecardDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
            completion_rate_score=90,
            response_sla_score=80,
            overall_score=85,
            is_routable=False,
        )
        svc.create = AsyncMock(return_value=created)

        result = await svc.rollup_period(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
        )

        self.assertEqual(result.overall_score, 85)
        self.assertFalse(result.is_routable)
        payload = svc.create.await_args.args[0]
        self.assertEqual(payload["status_flags"]["sample_size_total"], 4)
        self.assertEqual(payload["status_flags"]["policy"]["min_sample_size"], 5)

    async def test_rollup_period_normalizes_enum_values_from_storage(self) -> None:
        """Rollup should accept SQLAlchemy enum instances from DB rows."""
        tenant_id = uuid.uuid4()
        vendor_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=7)
        period_end = now

        rsg = Mock()
        rsg.find_many = AsyncMock(
            return_value=[
                {
                    "metric_type": VendorMetricType.COMPLETION_RATE,
                    "metric_numerator": 9,
                    "metric_denominator": 10,
                    "sample_size": 10,
                }
            ]
        )

        async def _get_one(table, where, columns=None):  # noqa: ANN001, ANN202
            if table == "ops_vpn_vendor":
                return {
                    "status": VendorLifecycleStatus.ACTIVE,
                    "next_reverification_due_at": now + timedelta(days=30),
                }
            if table == "ops_vpn_scorecard_policy":
                return None
            return None

        rsg.get_one = AsyncMock(side_effect=_get_one)

        svc = VendorScorecardService(table="ops_vpn_vendor_scorecard", rsg=rsg)
        svc.get = AsyncMock(return_value=None)
        created = VendorScorecardDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
            completion_rate_score=90,
            overall_score=90,
            is_routable=True,
        )
        svc.create = AsyncMock(return_value=created)

        result = await svc.rollup_period(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
        )

        self.assertEqual(result.overall_score, 90)
        self.assertTrue(result.is_routable)
        payload = svc.create.await_args.args[0]
        self.assertEqual(payload["completion_rate_score"], 90)
        self.assertEqual(payload["overall_score"], 90)
        self.assertEqual(payload["status_flags"]["vendor_status"], "active")
        self.assertNotIn("completion_rate", payload["status_flags"]["missing_metrics"])
