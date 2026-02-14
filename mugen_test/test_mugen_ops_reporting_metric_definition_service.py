"""Branch coverage tests for ops_reporting MetricDefinitionService."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_reporting.api.validation import (
    MetricRecomputeWindowValidation,
    MetricRunAggregationValidation,
)
from mugen.core.plugin.ops_reporting.domain import AggregationJobDE, MetricDefinitionDE
from mugen.core.plugin.ops_reporting.service import metric_definition as metric_mod
from mugen.core.plugin.ops_reporting.service.metric_definition import (
    MetricDefinitionService,
)


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _metric(
    *,
    metric_id: uuid.UUID | None = None,
    formula_type: str = "count_rows",
    source_table: str | None = "ops_case_case",
    source_time_column: str | None = "created_at",
    source_value_column: str | None = None,
    scope_column: str | None = None,
    source_filter=None,
) -> MetricDefinitionDE:
    return MetricDefinitionDE(
        id=metric_id or uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        formula_type=formula_type,
        source_table=source_table,
        source_time_column=source_time_column,
        source_value_column=source_value_column,
        scope_column=scope_column,
        source_filter=source_filter,
    )


class TestMugenOpsReportingMetricDefinitionService(unittest.IsolatedAsyncioTestCase):
    """Covers static helpers, action wrappers, and failure branches."""

    def test_static_helper_branches(self) -> None:
        naive = datetime(2026, 2, 14, 10, 0)
        aware = datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(
            MetricDefinitionService._to_aware_utc(naive).tzinfo,
            timezone.utc,
        )
        self.assertEqual(
            MetricDefinitionService._to_aware_utc(aware).tzinfo,
            timezone.utc,
        )

        self.assertEqual(MetricDefinitionService._normalize_scope_key(None), "__all__")
        self.assertEqual(
            MetricDefinitionService._normalize_scope_key("  "),
            "__all__",
        )
        self.assertEqual(
            MetricDefinitionService._normalize_scope_key(" team "),
            "team",
        )

        self.assertIsNone(MetricDefinitionService._coerce_numeric(None))
        self.assertEqual(MetricDefinitionService._coerce_numeric(True), 1)
        self.assertEqual(MetricDefinitionService._coerce_numeric(7), 7)
        self.assertEqual(MetricDefinitionService._coerce_numeric(2.6), 3)
        self.assertEqual(MetricDefinitionService._coerce_numeric("9"), 9)
        self.assertIsNone(MetricDefinitionService._coerce_numeric("x"))

        self.assertTrue(
            MetricDefinitionService._formula_requires_value_column("sum_column")
        )
        self.assertFalse(
            MetricDefinitionService._formula_requires_value_column("count_rows")
        )

        with patch.object(metric_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                MetricDefinitionService._bucket_windows(
                    window_start=aware,
                    window_end=aware,
                    bucket_minutes=60,
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                MetricDefinitionService._bucket_windows(
                    window_start=aware,
                    window_end=aware.replace(hour=11),
                    bucket_minutes=0,
                )
            self.assertEqual(ex.exception.code, 400)

    def test_window_resolution_and_bucket_value_branches(self) -> None:
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        default_data = MetricRunAggregationValidation(row_version=1)
        start, end = MetricDefinitionService._resolve_window_for_run(
            data=default_data,
            now=now,
        )
        self.assertEqual(end, now)
        self.assertEqual(start, now.replace(hour=11))

        provided = SimpleNamespace(
            window_start=datetime(2026, 2, 14, 10, 0),
            window_end=datetime(2026, 2, 14, 11, 0),
        )
        start, end = MetricDefinitionService._resolve_window_for_run(
            data=provided, now=now
        )
        self.assertEqual(start.tzinfo, timezone.utc)
        self.assertEqual(end.tzinfo, timezone.utc)

        with patch.object(metric_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                MetricDefinitionService._resolve_window_for_run(
                    data=SimpleNamespace(window_start=now, window_end=None),
                    now=now,
                )
            self.assertEqual(ex.exception.code, 400)

            class _FlakyWindow:
                def __init__(self) -> None:
                    self._start_calls = 0

                @property
                def window_start(self):
                    self._start_calls += 1
                    if self._start_calls >= 3:
                        return None
                    return now

                @property
                def window_end(self):
                    return now

            with self.assertRaises(_AbortCalled) as ex:
                MetricDefinitionService._resolve_window_for_run(
                    data=_FlakyWindow(),
                    now=now,
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                MetricDefinitionService._compute_bucket_value(
                    rows=[{"value": 1}],
                    formula_type="sum_column",
                    value_column=None,
                )
            self.assertEqual(ex.exception.code, 409)

            with self.assertRaises(_AbortCalled) as ex:
                MetricDefinitionService._compute_bucket_value(
                    rows=[{"value": 1}],
                    formula_type="unsupported",
                    value_column="value",
                )
            self.assertEqual(ex.exception.code, 409)

        self.assertEqual(
            MetricDefinitionService._compute_bucket_value(
                rows=[{"value": 1}, {"value": 2}],
                formula_type="count_rows",
                value_column=None,
            ),
            (2, 2),
        )
        self.assertEqual(
            MetricDefinitionService._compute_bucket_value(
                rows=[{"value": 1}, {"value": 2}],
                formula_type="sum_column",
                value_column="value",
            ),
            (3, 2),
        )
        self.assertEqual(
            MetricDefinitionService._compute_bucket_value(
                rows=[{"value": 1}, {"value": 2}],
                formula_type="avg_column",
                value_column="value",
            ),
            (2, 2),
        )
        self.assertEqual(
            MetricDefinitionService._compute_bucket_value(
                rows=[{"value": 1}, {"value": 2}],
                formula_type="min_column",
                value_column="value",
            ),
            (1, 2),
        )
        self.assertEqual(
            MetricDefinitionService._compute_bucket_value(
                rows=[{"value": 1}, {"value": 2}],
                formula_type="max_column",
                value_column="value",
            ),
            (2, 2),
        )
        self.assertEqual(
            MetricDefinitionService._compute_bucket_value(
                rows=[{"value": "bad"}],
                formula_type="sum_column",
                value_column="value",
            ),
            (0, 1),
        )

    async def test_get_for_action_and_update_with_row_version_branches(self) -> None:
        svc = MetricDefinitionService(
            table="ops_reporting_metric_definition", rsg=Mock()
        )
        target = _metric()
        where = {"id": target.id}

        svc.get = AsyncMock(side_effect=[target])
        current = await svc._get_for_action(where=where, expected_row_version=3)
        self.assertEqual(current.id, target.id)

        with patch.object(metric_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, None])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(side_effect=[None, target])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 500)

        updated = _metric(metric_id=target.id)
        svc.update_with_row_version = AsyncMock(return_value=updated)
        result = await svc._update_metric_with_row_version(
            where=where,
            expected_row_version=4,
            changes={"name": "updated"},
        )
        self.assertEqual(result.id, target.id)

        with patch.object(metric_mod, "abort", side_effect=_abort_raiser):
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("rv")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_metric_with_row_version(
                    where=where,
                    expected_row_version=4,
                    changes={"name": "updated"},
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_metric_with_row_version(
                    where=where,
                    expected_row_version=4,
                    changes={"name": "updated"},
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_metric_with_row_version(
                    where=where,
                    expected_row_version=4,
                    changes={"name": "updated"},
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_job_status_and_series_upsert_branches(self) -> None:
        svc = MetricDefinitionService(
            table="ops_reporting_metric_definition", rsg=Mock()
        )
        tenant_id = uuid.uuid4()

        job = AggregationJobDE(id=None, tenant_id=tenant_id, status="pending")
        svc._job_service.update = AsyncMock()
        await svc._set_job_status(
            tenant_id=tenant_id,
            job=job,
            status="running",
        )
        svc._job_service.update.assert_not_called()

        job.id = uuid.uuid4()
        await svc._set_job_status(
            tenant_id=tenant_id,
            job=job,
            status="completed",
            finished_at=datetime.now(timezone.utc),
        )
        svc._job_service.update.assert_awaited()

        metric_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        svc._series_service.get = AsyncMock(return_value=None)
        svc._series_service.create = AsyncMock()
        svc._series_service.update = AsyncMock()
        await svc._upsert_series_row(
            tenant_id=tenant_id,
            metric_definition_id=metric_id,
            bucket_start=now,
            bucket_end=now.replace(hour=now.hour + 1),
            scope_key="__all__",
            value_numeric=3,
            source_count=2,
            computed_at=now,
        )
        svc._series_service.create.assert_awaited_once()
        svc._series_service.update.assert_not_called()

        svc._series_service.get = AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        await svc._upsert_series_row(
            tenant_id=tenant_id,
            metric_definition_id=metric_id,
            bucket_start=now,
            bucket_end=now.replace(hour=now.hour + 1),
            scope_key="team",
            value_numeric=3,
            source_count=2,
            computed_at=now,
        )
        svc._series_service.update.assert_awaited_once()

    async def test_run_aggregation_and_action_branches(self) -> None:
        svc = MetricDefinitionService(
            table="ops_reporting_metric_definition", rsg=Mock()
        )
        tenant_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        window_start = datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 2, 14, 11, 0, tzinfo=timezone.utc)

        metric = _metric(metric_id=uuid.uuid4(), formula_type="count_rows")
        metric.scope_column = "channel"
        metric.source_filter = "not-a-dict"

        pending_job = AggregationJobDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            status="pending",
        )
        svc._job_service.get = AsyncMock(return_value=pending_job)
        svc._job_service.create = AsyncMock(return_value=pending_job)
        svc._job_service.update = AsyncMock(return_value=pending_job)
        svc._series_service.get = AsyncMock(return_value=None)
        svc._series_service.create = AsyncMock()
        svc._series_service.update = AsyncMock()
        svc._rsg.find_many = AsyncMock(return_value=[{"id": uuid.uuid4()}])

        await svc._run_aggregation(
            metric=metric,
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            window_start=window_start,
            window_end=window_end,
            bucket_minutes=60,
            scope_key="chat",
            force_recompute=True,
        )
        svc._job_service.create.assert_not_called()
        self.assertIn(
            "channel",
            svc._rsg.find_many.await_args.kwargs["filter_groups"][0].where,
        )

        with patch.object(metric_mod, "abort", side_effect=_abort_raiser):
            missing_id_metric = _metric()
            missing_id_metric.id = None
            with self.assertRaises(_AbortCalled) as ex:
                await svc._run_aggregation(
                    metric=missing_id_metric,
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    window_start=window_start,
                    window_end=window_end,
                    bucket_minutes=60,
                    scope_key="__all__",
                    force_recompute=True,
                )
            self.assertEqual(ex.exception.code, 409)

            with self.assertRaises(_AbortCalled) as ex:
                await svc._run_aggregation(
                    metric=_metric(source_table=" "),
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    window_start=window_start,
                    window_end=window_end,
                    bucket_minutes=60,
                    scope_key="__all__",
                    force_recompute=True,
                )
            self.assertEqual(ex.exception.code, 409)

            with self.assertRaises(_AbortCalled) as ex:
                await svc._run_aggregation(
                    metric=_metric(formula_type="sum_column", source_value_column=None),
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    window_start=window_start,
                    window_end=window_end,
                    bucket_minutes=60,
                    scope_key="__all__",
                    force_recompute=True,
                )
            self.assertEqual(ex.exception.code, 409)

            with self.assertRaises(_AbortCalled) as ex:
                await svc._run_aggregation(
                    metric=_metric(source_time_column=" "),
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    window_start=window_start,
                    window_end=window_end,
                    bucket_minutes=60,
                    scope_key="__all__",
                    force_recompute=True,
                )
            self.assertEqual(ex.exception.code, 409)

        failing_metric = _metric()
        job = AggregationJobDE(id=uuid.uuid4(), tenant_id=tenant_id, status="pending")
        svc._job_service.get = AsyncMock(return_value=None)
        svc._job_service.create = AsyncMock(return_value=job)
        svc._job_service.update = AsyncMock(return_value=job)

        with patch.object(metric_mod, "abort", side_effect=_abort_raiser):
            svc._rsg.find_many = AsyncMock(side_effect=KeyError("missing-col"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._run_aggregation(
                    metric=failing_metric,
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    window_start=window_start,
                    window_end=window_end,
                    bucket_minutes=60,
                    scope_key="__all__",
                    force_recompute=True,
                )
            self.assertEqual(ex.exception.code, 409)
            self.assertEqual(
                svc._job_service.update.await_args.kwargs["changes"]["error_message"],
                "'missing-col'",
            )

            long_key = "x" * 1500
            svc._rsg.find_many = AsyncMock(side_effect=KeyError(long_key))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._run_aggregation(
                    metric=failing_metric,
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    window_start=window_start,
                    window_end=window_end,
                    bucket_minutes=60,
                    scope_key="__all__",
                    force_recompute=True,
                )
            self.assertEqual(ex.exception.code, 409)
            self.assertEqual(
                len(svc._job_service.update.await_args.kwargs["changes"]["error_message"]),
                1024,
            )

            svc._rsg.find_many = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._run_aggregation(
                    metric=failing_metric,
                    tenant_id=tenant_id,
                    auth_user_id=auth_user_id,
                    window_start=window_start,
                    window_end=window_end,
                    bucket_minutes=60,
                    scope_key="__all__",
                    force_recompute=True,
                )
            self.assertEqual(ex.exception.code, 500)

        metric_for_actions = _metric(metric_id=uuid.uuid4(), formula_type="count_rows")
        svc._get_for_action = AsyncMock(return_value=metric_for_actions)
        svc._run_aggregation = AsyncMock(return_value=None)
        svc._now_utc = Mock(return_value=now)

        payload = MetricRunAggregationValidation(row_version=3, bucket_minutes=15)
        body, status = await svc.action_run_aggregation(
            tenant_id=tenant_id,
            entity_id=metric_for_actions.id,
            where={"id": metric_for_actions.id},
            auth_user_id=auth_user_id,
            data=payload,
        )
        self.assertEqual((body, status), ("", 204))

        with patch.object(metric_mod, "abort", side_effect=_abort_raiser):
            invalid_window_data = SimpleNamespace(
                row_version=3,
                bucket_minutes=15,
                scope_key=None,
                window_start=now,
                window_end=now,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_run_aggregation(
                    tenant_id=tenant_id,
                    entity_id=metric_for_actions.id,
                    where={"id": metric_for_actions.id},
                    auth_user_id=auth_user_id,
                    data=invalid_window_data,
                )
            self.assertEqual(ex.exception.code, 400)

        recompute = MetricRecomputeWindowValidation(
            row_version=4,
            window_start=window_start,
            window_end=window_end,
            bucket_minutes=60,
        )
        body, status = await svc.action_recompute_window(
            tenant_id=tenant_id,
            entity_id=metric_for_actions.id,
            where={"id": metric_for_actions.id},
            auth_user_id=auth_user_id,
            data=recompute,
        )
        self.assertEqual((body, status), ("", 204))

        with patch.object(metric_mod, "abort", side_effect=_abort_raiser):
            invalid_recompute = SimpleNamespace(
                row_version=4,
                window_start=now,
                window_end=now,
                bucket_minutes=60,
                scope_key=None,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_recompute_window(
                    tenant_id=tenant_id,
                    entity_id=metric_for_actions.id,
                    where={"id": metric_for_actions.id},
                    auth_user_id=auth_user_id,
                    data=invalid_recompute,
                )
            self.assertEqual(ex.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
