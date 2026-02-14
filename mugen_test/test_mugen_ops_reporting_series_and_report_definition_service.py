"""Branch tests for ops_reporting metric-series and report-definition services."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
import uuid
from unittest.mock import AsyncMock, Mock

from sqlalchemy.exc import IntegrityError

from mugen.core.plugin.ops_reporting.service.metric_series import MetricSeriesService
from mugen.core.plugin.ops_reporting.service.report_definition import (
    ReportDefinitionService,
)


class TestMugenOpsReportingSeriesAndReportDefinitionService(
    unittest.IsolatedAsyncioTestCase
):
    """Covers branch paths in lightweight ops_reporting services."""

    async def test_metric_series_service_branches(self) -> None:
        tenant_id = uuid.uuid4()
        metric_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(
            MetricSeriesService._normalize_scope_key(None),
            "__all__",
        )
        self.assertEqual(
            MetricSeriesService._normalize_scope_key(" team "),
            "team",
        )
        self.assertIsNotNone(MetricSeriesService._now_utc().tzinfo)

        rsg = Mock()
        svc = MetricSeriesService(table="ops_reporting_metric_series", rsg=rsg)

        existing = svc._from_record(
            {"id": uuid.uuid4(), "tenant_id": tenant_id, "aggregation_key": "k"}
        )
        svc.get = AsyncMock(return_value=existing)
        rsg.insert_one = AsyncMock()
        got = await svc.create(
            {
                "tenant_id": tenant_id,
                "metric_definition_id": metric_id,
                "bucket_start": now,
                "bucket_end": now.replace(hour=13),
                "scope_key": " ",
                "source_count": 1,
                "value_numeric": 2,
                "aggregation_key": "k",
            }
        )
        self.assertEqual(got.id, existing.id)
        rsg.insert_one.assert_not_called()

        svc.get = AsyncMock(return_value=None)
        rsg.insert_one = AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "metric_definition_id": metric_id,
                "scope_key": "__all__",
                "source_count": 0,
                "value_numeric": 0,
                "computed_at": now,
                "aggregation_key": "",
            }
        )
        created = await svc.create(
            {
                "tenant_id": None,
                "metric_definition_id": metric_id,
                "bucket_start": now,
                "bucket_end": now.replace(hour=13),
                "scope_key": "",
                "source_count": None,
                "value_numeric": None,
                "aggregation_key": " ",
            }
        )
        self.assertEqual(created.scope_key, "__all__")
        insert_payload = rsg.insert_one.await_args.args[1]
        self.assertEqual(insert_payload["source_count"], 0)
        self.assertEqual(insert_payload["value_numeric"], 0)
        self.assertEqual(insert_payload["aggregation_key"], "")
        self.assertIsNotNone(insert_payload["computed_at"])

        raced = {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "metric_definition_id": metric_id,
            "aggregation_key": "k",
        }
        svc.get = AsyncMock(
            side_effect=[None, svc._from_record(raced)]
        )  # type: ignore[arg-type]
        rsg.insert_one = AsyncMock(side_effect=IntegrityError("ins", {}, None))
        result = await svc.create(
            {
                "tenant_id": tenant_id,
                "metric_definition_id": metric_id,
                "bucket_start": now,
                "bucket_end": now.replace(hour=13),
                "scope_key": "x",
                "source_count": 1,
                "value_numeric": 2,
                "aggregation_key": "k",
            }
        )
        self.assertEqual(result.aggregation_key, "k")

        svc.get = AsyncMock(side_effect=[None, None])
        rsg.insert_one = AsyncMock(side_effect=IntegrityError("ins", {}, None))
        with self.assertRaises(IntegrityError):
            await svc.create(
                {
                    "tenant_id": tenant_id,
                    "metric_definition_id": metric_id,
                    "bucket_start": now,
                    "bucket_end": now.replace(hour=13),
                    "scope_key": "x",
                    "source_count": 1,
                    "value_numeric": 2,
                    "aggregation_key": "k",
                }
            )

        svc.get = AsyncMock(return_value=None)
        rsg.insert_one = AsyncMock(side_effect=IntegrityError("ins", {}, None))
        with self.assertRaises(IntegrityError):
            await svc.create(
                {
                    "tenant_id": None,
                    "metric_definition_id": metric_id,
                    "bucket_start": now,
                    "bucket_end": now.replace(hour=13),
                    "scope_key": "x",
                    "source_count": 1,
                    "value_numeric": 2,
                    "aggregation_key": "k",
                }
            )

    async def test_report_definition_service_create_cleans_metric_codes(self) -> None:
        rsg = Mock()
        svc = ReportDefinitionService(table="ops_reporting_report_definition", rsg=rsg)

        tenant_id = uuid.uuid4()
        inserted_id = uuid.uuid4()
        rsg.insert_one = AsyncMock(
            return_value={
                "id": inserted_id,
                "tenant_id": tenant_id,
                "code": "ops",
                "name": "Ops Report",
                "metric_codes": ["A", "B"],
            }
        )

        created = await svc.create(
            {
                "tenant_id": tenant_id,
                "code": "ops",
                "name": "Ops Report",
                "metric_codes": [" A ", "", None, "B"],
            }
        )
        self.assertEqual(created.id, inserted_id)
        payload = rsg.insert_one.await_args.args[1]
        self.assertEqual(payload["metric_codes"], ["A", "B"])

        rsg.insert_one = AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "code": "ops-2",
                "name": "Ops Report 2",
            }
        )
        created = await svc.create(
            {
                "tenant_id": tenant_id,
                "code": "ops-2",
                "name": "Ops Report 2",
                "metric_codes": None,
            }
        )
        self.assertEqual(created.code, "ops-2")
        payload = rsg.insert_one.await_args.args[1]
        self.assertIsNone(payload["metric_codes"])


if __name__ == "__main__":
    unittest.main()
