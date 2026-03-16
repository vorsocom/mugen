"""Provides a CRUD service for metric definitions and aggregation actions."""

__all__ = ["MetricDefinitionService"]

from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.ops_reporting.api.validation import (
    MetricRecomputeWindowValidation,
    MetricRunAggregationValidation,
)
from mugen.core.plugin.ops_reporting.contract.service.metric_definition import (
    IMetricDefinitionService,
)
from mugen.core.plugin.ops_reporting.domain import AggregationJobDE, MetricDefinitionDE
from mugen.core.plugin.ops_reporting.service.aggregation_job import (
    AggregationJobService,
)
from mugen.core.plugin.ops_reporting.service.metric_series import MetricSeriesService


class MetricDefinitionService(
    IRelationalService[MetricDefinitionDE],
    IMetricDefinitionService,
):
    """A CRUD service for metric definitions and deterministic aggregation actions."""

    _SERIES_TABLE = "ops_reporting_metric_series"
    _JOB_TABLE = "ops_reporting_aggregation_job"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=MetricDefinitionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._series_service = MetricSeriesService(table=self._SERIES_TABLE, rsg=rsg)
        self._job_service = AggregationJobService(table=self._JOB_TABLE, rsg=rsg)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_scope_key(value: str | None) -> str:
        clean = str(value or "").strip()
        return clean or "__all__"

    @classmethod
    def _window_key(
        cls,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> str:
        return (
            f"{cls._to_aware_utc(window_start).isoformat()}|"
            f"{cls._to_aware_utc(window_end).isoformat()}"
        )

    @classmethod
    def _series_key(
        cls,
        *,
        metric_definition_id: uuid.UUID,
        bucket_start: datetime,
        bucket_end: datetime,
        scope_key: str,
    ) -> str:
        return (
            f"{metric_definition_id}:"
            f"{cls._to_aware_utc(bucket_start).isoformat()}:"
            f"{cls._to_aware_utc(bucket_end).isoformat()}:"
            f"{scope_key}"
        )

    @classmethod
    def _job_key(
        cls,
        *,
        metric_definition_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        scope_key: str,
    ) -> str:
        return (
            f"{metric_definition_id}:"
            f"{cls._window_key(window_start=window_start, window_end=window_end)}:"
            f"{scope_key}"
        )

    @staticmethod
    def _coerce_numeric(value: Any) -> int | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return int(value)

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(round(value))

        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _formula_requires_value_column(formula_type: str) -> bool:
        return formula_type in {"sum_column", "avg_column", "min_column", "max_column"}

    @classmethod
    def _bucket_windows(
        cls,
        *,
        window_start: datetime,
        window_end: datetime,
        bucket_minutes: int,
    ) -> list[tuple[datetime, datetime]]:
        start = cls._to_aware_utc(window_start)
        end = cls._to_aware_utc(window_end)

        if end <= start:
            abort(400, "WindowEnd must be > WindowStart.")

        if bucket_minutes <= 0:
            abort(400, "BucketMinutes must be > 0.")

        buckets: list[tuple[datetime, datetime]] = []
        delta = timedelta(minutes=int(bucket_minutes))

        cursor = start
        while cursor < end:
            bucket_end = min(cursor + delta, end)
            buckets.append((cursor, bucket_end))
            cursor = bucket_end

        return buckets

    @classmethod
    def _resolve_window_for_run(
        cls,
        *,
        data: MetricRunAggregationValidation,
        now: datetime,
    ) -> tuple[datetime, datetime]:
        if data.window_start is None and data.window_end is None:
            return now - timedelta(hours=1), now

        if (data.window_start is None) != (data.window_end is None):
            abort(400, "Provide both WindowStart and WindowEnd together.")

        if data.window_start is None or data.window_end is None:
            abort(400, "WindowStart and WindowEnd are required.")

        return cls._to_aware_utc(data.window_start), cls._to_aware_utc(data.window_end)

    @staticmethod
    def _compute_bucket_value(
        *,
        rows: list[Mapping[str, Any]],
        formula_type: str,
        value_column: str | None,
    ) -> tuple[int, int]:
        source_count = len(rows)

        if formula_type == "count_rows":
            return source_count, source_count

        if not value_column:
            abort(409, "SourceValueColumn is required for this FormulaType.")

        values: list[int] = []
        for row in rows:
            numeric = MetricDefinitionService._coerce_numeric(row.get(value_column))
            if numeric is None:
                continue
            values.append(numeric)

        if not values:
            return 0, source_count

        if formula_type == "sum_column":
            return int(sum(values)), source_count
        if formula_type == "avg_column":
            return int(round(sum(values) / len(values))), source_count
        if formula_type == "min_column":
            return int(min(values)), source_count
        if formula_type == "max_column":
            return int(max(values)), source_count

        abort(409, f"Unsupported FormulaType: {formula_type}.")

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> MetricDefinitionDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Metric definition not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _set_job_status(
        self,
        *,
        tenant_id: uuid.UUID,
        job: AggregationJobDE,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        last_run_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        if job.id is None:
            return

        changes: dict[str, Any] = {
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "last_run_at": last_run_at,
            "error_message": error_message,
        }

        await self._job_service.update(
            where={
                "tenant_id": tenant_id,
                "id": job.id,
            },
            changes=changes,
        )

    async def _upsert_series_row(
        self,
        *,
        tenant_id: uuid.UUID,
        metric_definition_id: uuid.UUID,
        bucket_start: datetime,
        bucket_end: datetime,
        scope_key: str,
        value_numeric: int,
        source_count: int,
        computed_at: datetime,
    ) -> None:
        aggregation_key = self._series_key(
            metric_definition_id=metric_definition_id,
            bucket_start=bucket_start,
            bucket_end=bucket_end,
            scope_key=scope_key,
        )

        existing = await self._series_service.get(
            {
                "tenant_id": tenant_id,
                "aggregation_key": aggregation_key,
            }
        )

        payload: dict[str, Any] = {
            "metric_definition_id": metric_definition_id,
            "bucket_start": bucket_start,
            "bucket_end": bucket_end,
            "scope_key": scope_key,
            "value_numeric": int(value_numeric),
            "source_count": int(source_count),
            "computed_at": computed_at,
            "aggregation_key": aggregation_key,
        }

        if existing is None:
            payload["tenant_id"] = tenant_id
            await self._series_service.create(payload)
            return

        await self._series_service.update(
            where={
                "tenant_id": tenant_id,
                "id": existing.id,
            },
            changes=payload,
        )

    async def _run_aggregation(
        self,
        *,
        metric: MetricDefinitionDE,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        bucket_minutes: int,
        scope_key: str,
        force_recompute: bool,
    ) -> None:
        if metric.id is None:
            abort(409, "Metric definition identifier is missing.")

        if not metric.source_table or not metric.source_table.strip():
            abort(409, "SourceTable is required for metric aggregation.")

        raw_formula_type = metric.formula_type
        if hasattr(raw_formula_type, "value"):
            raw_formula_type = getattr(raw_formula_type, "value")

        formula_type = str(raw_formula_type or "count_rows").strip().lower()

        if self._formula_requires_value_column(formula_type):
            if not (metric.source_value_column or "").strip():
                abort(409, "SourceValueColumn is required for this FormulaType.")

        source_time_column = str(metric.source_time_column or "created_at").strip()
        if not source_time_column:
            abort(409, "SourceTimeColumn cannot be empty.")

        source_value_column = (
            str(metric.source_value_column).strip()
            if metric.source_value_column is not None
            else None
        )

        job_key = self._job_key(
            metric_definition_id=metric.id,
            window_start=window_start,
            window_end=window_end,
            scope_key=scope_key,
        )

        existing_job = await self._job_service.get(
            where={
                "tenant_id": tenant_id,
                "idempotency_key": job_key,
            }
        )

        if (
            existing_job is not None
            and existing_job.status == "completed"
            and not force_recompute
        ):
            return

        now = self._now_utc()

        if existing_job is None:
            existing_job = await self._job_service.create(
                {
                    "tenant_id": tenant_id,
                    "metric_definition_id": metric.id,
                    "window_start": window_start,
                    "window_end": window_end,
                    "bucket_minutes": bucket_minutes,
                    "scope_key": scope_key,
                    "idempotency_key": job_key,
                    "status": "pending",
                    "created_by_user_id": auth_user_id,
                }
            )

        try:
            await self._set_job_status(
                tenant_id=tenant_id,
                job=existing_job,
                status="running",
                started_at=now,
                finished_at=None,
                error_message=None,
            )

            buckets = self._bucket_windows(
                window_start=window_start,
                window_end=window_end,
                bucket_minutes=bucket_minutes,
            )

            for bucket_start, bucket_end in buckets:
                where: dict[str, Any] = {}
                source_filter = metric.source_filter or {}
                if isinstance(source_filter, dict):
                    where.update(source_filter)

                where["tenant_id"] = tenant_id

                if metric.scope_column and scope_key != "__all__":
                    where[str(metric.scope_column)] = scope_key

                filter_group = FilterGroup(
                    where=where,
                    scalar_filters=(
                        ScalarFilter(
                            field=source_time_column,
                            op=ScalarFilterOp.GTE,
                            value=bucket_start,
                        ),
                        ScalarFilter(
                            field=source_time_column,
                            op=ScalarFilterOp.LT,
                            value=bucket_end,
                        ),
                    ),
                )

                columns: list[str] | None = None
                if formula_type != "count_rows" and source_value_column:
                    columns = [source_value_column]

                rows = await self._rsg.find_many(
                    str(metric.source_table),
                    columns=columns,
                    filter_groups=[filter_group],
                )

                value_numeric, source_count = self._compute_bucket_value(
                    rows=rows,
                    formula_type=formula_type,
                    value_column=source_value_column,
                )

                await self._upsert_series_row(
                    tenant_id=tenant_id,
                    metric_definition_id=metric.id,
                    bucket_start=bucket_start,
                    bucket_end=bucket_end,
                    scope_key=scope_key,
                    value_numeric=value_numeric,
                    source_count=source_count,
                    computed_at=now,
                )

            await self._set_job_status(
                tenant_id=tenant_id,
                job=existing_job,
                status="completed",
                finished_at=now,
                last_run_at=now,
                error_message=None,
            )

        except (KeyError, ValueError) as e:
            message = str(e)
            if len(message) > 1024:
                message = message[:1024]

            await self._set_job_status(
                tenant_id=tenant_id,
                job=existing_job,
                status="failed",
                finished_at=self._now_utc(),
                error_message=message,
            )
            abort(409, f"Invalid source binding for aggregation: {e}.")
        except SQLAlchemyError:
            await self._set_job_status(
                tenant_id=tenant_id,
                job=existing_job,
                status="failed",
                finished_at=self._now_utc(),
                error_message="Storage failure during aggregation.",
            )
            abort(500)

    async def action_run_aggregation(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: MetricRunAggregationValidation,
    ) -> tuple[dict[str, Any], int]:
        """Run deterministic aggregation for a metric over one window."""
        _ = entity_id

        expected_row_version = int(data.row_version)

        metric = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        now = self._now_utc()
        window_start, window_end = self._resolve_window_for_run(data=data, now=now)

        if window_end <= window_start:
            abort(400, "WindowEnd must be > WindowStart.")

        await self._run_aggregation(
            metric=metric,
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            window_start=window_start,
            window_end=window_end,
            bucket_minutes=int(data.bucket_minutes),
            scope_key=self._normalize_scope_key(data.scope_key),
            force_recompute=False,
        )

        return "", 204

    async def action_recompute_window(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: MetricRecomputeWindowValidation,
    ) -> tuple[dict[str, Any], int]:
        """Force window recomputation for a metric and scope."""
        _ = entity_id

        expected_row_version = int(data.row_version)

        metric = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        window_start = self._to_aware_utc(data.window_start)
        window_end = self._to_aware_utc(data.window_end)

        if window_end <= window_start:
            abort(400, "WindowEnd must be > WindowStart.")

        await self._run_aggregation(
            metric=metric,
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            window_start=window_start,
            window_end=window_end,
            bucket_minutes=int(data.bucket_minutes),
            scope_key=self._normalize_scope_key(data.scope_key),
            force_recompute=True,
        )

        return "", 204

    async def _update_metric_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> MetricDefinitionDE:
        svc: ICrudServiceWithRowVersion[MetricDefinitionDE] = self

        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return updated
