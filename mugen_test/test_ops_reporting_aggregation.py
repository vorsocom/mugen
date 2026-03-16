"""Unit tests for ops_reporting aggregation correctness and idempotency."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.ops_reporting.domain import AggregationJobDE, MetricDefinitionDE
from mugen.core.plugin.ops_reporting.model.metric_definition import MetricFormulaType
from mugen.core.plugin.ops_reporting.service.metric_definition import (
    MetricDefinitionService,
)


class TestOpsReportingAggregation(unittest.IsolatedAsyncioTestCase):
    """Tests deterministic aggregation behavior on MetricDefinitionService."""

    async def test_run_aggregation_is_idempotent_for_completed_job(self) -> None:
        tenant_id = uuid.uuid4()
        metric_id = uuid.uuid4()

        svc = MetricDefinitionService(
            table="ops_reporting_metric_definition",
            rsg=Mock(),
        )

        metric = MetricDefinitionDE(
            id=metric_id,
            tenant_id=tenant_id,
            formula_type="count_rows",
            source_table="ops_case_case",
        )

        svc._job_service.get = AsyncMock(
            return_value=AggregationJobDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                metric_definition_id=metric_id,
                status="completed",
            )
        )
        svc._rsg.find_many = AsyncMock()

        await svc._run_aggregation(
            metric=metric,
            tenant_id=tenant_id,
            auth_user_id=uuid.uuid4(),
            window_start=datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 2, 14, 11, 0, tzinfo=timezone.utc),
            bucket_minutes=60,
            scope_key="__all__",
            force_recompute=False,
        )

        svc._rsg.find_many.assert_not_called()

    async def test_bucketing_splits_boundary_rows_into_next_bucket(self) -> None:
        tenant_id = uuid.uuid4()
        metric_id = uuid.uuid4()

        svc = MetricDefinitionService(
            table="ops_reporting_metric_definition",
            rsg=Mock(),
        )

        metric = MetricDefinitionDE(
            id=metric_id,
            tenant_id=tenant_id,
            formula_type="sum_column",
            source_table="ops_case_case",
            source_time_column="occurred_at",
            source_value_column="value",
        )

        dataset = [
            {
                "occurred_at": datetime(2026, 2, 14, 10, 59, tzinfo=timezone.utc),
                "value": 2,
            },
            {
                "occurred_at": datetime(2026, 2, 14, 11, 0, tzinfo=timezone.utc),
                "value": 7,
            },
            {
                "occurred_at": datetime(2026, 2, 14, 11, 30, tzinfo=timezone.utc),
                "value": 1,
            },
        ]

        async def _find_many(*_args, **kwargs):
            filter_group = kwargs["filter_groups"][0]
            start = next(
                sf.value
                for sf in filter_group.scalar_filters
                if sf.field == "occurred_at" and sf.op.name == "GTE"
            )
            end = next(
                sf.value
                for sf in filter_group.scalar_filters
                if sf.field == "occurred_at" and sf.op.name == "LT"
            )
            rows = []
            for row in dataset:
                ts = row["occurred_at"]
                if start <= ts < end:
                    rows.append({"value": row["value"]})
            return rows

        svc._rsg.find_many = AsyncMock(side_effect=_find_many)

        job = AggregationJobDE(id=uuid.uuid4(), tenant_id=tenant_id, status="pending")
        svc._job_service.get = AsyncMock(return_value=None)
        svc._job_service.create = AsyncMock(return_value=job)
        svc._job_service.update = AsyncMock(return_value=job)

        svc._series_service.get = AsyncMock(side_effect=[None, None])
        svc._series_service.create = AsyncMock()
        svc._series_service.update = AsyncMock()

        await svc._run_aggregation(
            metric=metric,
            tenant_id=tenant_id,
            auth_user_id=uuid.uuid4(),
            window_start=datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc),
            bucket_minutes=60,
            scope_key="__all__",
            force_recompute=True,
        )

        self.assertEqual(svc._series_service.create.await_count, 2)

        first_payload = svc._series_service.create.await_args_list[0].args[0]
        second_payload = svc._series_service.create.await_args_list[1].args[0]

        self.assertEqual(first_payload["value_numeric"], 2)
        self.assertEqual(second_payload["value_numeric"], 8)

    async def test_count_rows_formula_accepts_enum_value(self) -> None:
        tenant_id = uuid.uuid4()
        metric_id = uuid.uuid4()

        svc = MetricDefinitionService(
            table="ops_reporting_metric_definition",
            rsg=Mock(),
        )

        metric = MetricDefinitionDE(
            id=metric_id,
            tenant_id=tenant_id,
            formula_type=MetricFormulaType.COUNT_ROWS,
            source_table="ops_case_case",
        )

        svc._rsg.find_many = AsyncMock(return_value=[{"id": uuid.uuid4()}])

        job = AggregationJobDE(id=uuid.uuid4(), tenant_id=tenant_id, status="pending")
        svc._job_service.get = AsyncMock(return_value=None)
        svc._job_service.create = AsyncMock(return_value=job)
        svc._job_service.update = AsyncMock(return_value=job)

        svc._series_service.get = AsyncMock(return_value=None)
        svc._series_service.create = AsyncMock()

        await svc._run_aggregation(
            metric=metric,
            tenant_id=tenant_id,
            auth_user_id=uuid.uuid4(),
            window_start=datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 2, 14, 11, 0, tzinfo=timezone.utc),
            bucket_minutes=60,
            scope_key="__all__",
            force_recompute=True,
        )

        payload = svc._series_service.create.await_args.args[0]
        self.assertEqual(payload["value_numeric"], 1)
