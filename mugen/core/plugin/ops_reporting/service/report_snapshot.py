"""Provides a CRUD service for report snapshot lifecycle actions."""

__all__ = ["ReportSnapshotService"]

from datetime import datetime, timezone
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
    ReportSnapshotArchiveValidation,
    ReportSnapshotGenerateValidation,
    ReportSnapshotPublishValidation,
)
from mugen.core.plugin.ops_reporting.contract.service.report_snapshot import (
    IReportSnapshotService,
)
from mugen.core.plugin.ops_reporting.domain import ReportSnapshotDE
from mugen.core.plugin.ops_reporting.service.metric_definition import (
    MetricDefinitionService,
)
from mugen.core.plugin.ops_reporting.service.metric_series import MetricSeriesService
from mugen.core.plugin.ops_reporting.service.report_definition import (
    ReportDefinitionService,
)


class ReportSnapshotService(
    IRelationalService[ReportSnapshotDE],
    IReportSnapshotService,
):
    """A CRUD service for report snapshot generation, publish, and archive."""

    _METRIC_DEFINITION_TABLE = "ops_reporting_metric_definition"
    _METRIC_SERIES_TABLE = "ops_reporting_metric_series"
    _REPORT_DEFINITION_TABLE = "ops_reporting_report_definition"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ReportSnapshotDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._metric_definition_service = MetricDefinitionService(
            table=self._METRIC_DEFINITION_TABLE,
            rsg=rsg,
        )
        self._metric_series_service = MetricSeriesService(
            table=self._METRIC_SERIES_TABLE,
            rsg=rsg,
        )
        self._report_definition_service = ReportDefinitionService(
            table=self._REPORT_DEFINITION_TABLE,
            rsg=rsg,
        )

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

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _normalize_metric_codes(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []

        codes: list[str] = []
        for item in raw:
            clean = str(item or "").strip()
            if clean:
                codes.append(clean)

        return list(dict.fromkeys(codes))

    async def create(self, values: Mapping[str, Any]) -> ReportSnapshotDE:
        create_values = dict(values)

        create_values["scope_key"] = self._normalize_scope_key(
            create_values.get("scope_key")
        )

        metric_codes = create_values.get("metric_codes")
        if metric_codes is not None:
            create_values["metric_codes"] = self._normalize_metric_codes(metric_codes)

        if not create_values.get("status"):
            create_values["status"] = "draft"

        create_values["note"] = self._normalize_optional_text(create_values.get("note"))

        return await super().create(create_values)

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> ReportSnapshotDE:
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
            abort(404, "Report snapshot not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_snapshot_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> ReportSnapshotDE:
        svc: ICrudServiceWithRowVersion[ReportSnapshotDE] = self

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

    async def _resolve_metric_codes(
        self,
        *,
        tenant_id: uuid.UUID,
        snapshot: ReportSnapshotDE,
    ) -> list[str]:
        codes = self._normalize_metric_codes(snapshot.metric_codes)
        if codes:
            return codes

        if snapshot.report_definition_id is None:
            abort(409, "Snapshot has no ReportDefinitionId or MetricCodes.")

        report_definition = await self._report_definition_service.get(
            {
                "tenant_id": tenant_id,
                "id": snapshot.report_definition_id,
            }
        )
        if report_definition is None:
            abort(409, "ReportDefinitionId does not resolve to an existing report.")

        report_codes = self._normalize_metric_codes(report_definition.metric_codes)
        if not report_codes:
            abort(409, "Resolved report definition has no MetricCodes.")

        return report_codes

    def _resolve_window(
        self,
        *,
        snapshot: ReportSnapshotDE,
        data: ReportSnapshotGenerateValidation,
    ) -> tuple[datetime, datetime]:
        window_start = data.window_start or snapshot.window_start
        window_end = data.window_end or snapshot.window_end

        if window_start is None or window_end is None:
            abort(
                409,
                "Provide WindowStart and WindowEnd on snapshot or action payload.",
            )

        window_start = self._to_aware_utc(window_start)
        window_end = self._to_aware_utc(window_end)

        if window_end <= window_start:
            abort(400, "WindowEnd must be > WindowStart.")

        return window_start, window_end

    async def _build_metric_summary(
        self,
        *,
        tenant_id: uuid.UUID,
        metric_codes: list[str],
        window_start: datetime,
        window_end: datetime,
        scope_key: str,
    ) -> list[dict[str, Any]]:
        metrics: list[dict[str, Any]] = []

        for code in metric_codes:
            metric_definition = await self._metric_definition_service.get(
                {
                    "tenant_id": tenant_id,
                    "code": code,
                }
            )

            if metric_definition is None or metric_definition.id is None:
                metrics.append(
                    {
                        "metric_code": code,
                        "metric_name": None,
                        "missing_metric_definition": True,
                        "bucket_count": 0,
                        "source_count": 0,
                        "value_numeric": 0,
                    }
                )
                continue

            rows = await self._metric_series_service.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "metric_definition_id": metric_definition.id,
                            "scope_key": scope_key,
                        },
                        scalar_filters=(
                            ScalarFilter(
                                field="bucket_start",
                                op=ScalarFilterOp.GTE,
                                value=window_start,
                            ),
                            ScalarFilter(
                                field="bucket_end",
                                op=ScalarFilterOp.LTE,
                                value=window_end,
                            ),
                        ),
                    )
                ]
            )

            value_numeric = sum(int(row.value_numeric or 0) for row in rows)
            source_count = sum(int(row.source_count or 0) for row in rows)

            last_computed = None
            for row in rows:
                if row.computed_at is None:
                    continue
                if last_computed is None or row.computed_at > last_computed:
                    last_computed = row.computed_at

            metrics.append(
                {
                    "metric_code": code,
                    "metric_name": metric_definition.name,
                    "missing_metric_definition": False,
                    "bucket_count": len(rows),
                    "source_count": source_count,
                    "value_numeric": value_numeric,
                    "last_computed_at": (
                        self._to_aware_utc(last_computed).isoformat()
                        if last_computed is not None
                        else None
                    ),
                }
            )

        return metrics

    async def action_generate_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ReportSnapshotGenerateValidation,
    ) -> tuple[dict[str, Any], int]:
        """Generate snapshot summary payload from metric-series rows."""
        _ = entity_id

        expected_row_version = int(data.row_version)

        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "archived":
            abort(409, "Archived snapshots cannot be regenerated.")

        metric_codes = await self._resolve_metric_codes(
            tenant_id=tenant_id,
            snapshot=current,
        )
        window_start, window_end = self._resolve_window(snapshot=current, data=data)
        scope_key = self._normalize_scope_key(data.scope_key or current.scope_key)

        metrics = await self._build_metric_summary(
            tenant_id=tenant_id,
            metric_codes=metric_codes,
            window_start=window_start,
            window_end=window_end,
            scope_key=scope_key,
        )

        now = self._now_utc()
        summary = {
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "scope_key": scope_key,
            "metric_count": len(metrics),
            "metrics": metrics,
            "generated_at": now.isoformat(),
        }

        await self._update_snapshot_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "generated",
                "window_start": window_start,
                "window_end": window_end,
                "scope_key": scope_key,
                "metric_codes": metric_codes,
                "summary_json": summary,
                "generated_at": now,
                "generated_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.note),
            },
        )

        return "", 204

    async def action_publish_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ReportSnapshotPublishValidation,
    ) -> tuple[dict[str, Any], int]:
        """Publish a generated report snapshot."""
        _ = tenant_id
        _ = entity_id

        expected_row_version = int(data.row_version)

        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "archived":
            abort(409, "Archived snapshots cannot be published.")

        if current.status == "published":
            return "", 204

        if current.status != "generated":
            abort(409, "Snapshot must be generated before publish.")

        now = self._now_utc()

        await self._update_snapshot_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "published",
                "published_at": now,
                "published_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.note),
            },
        )

        return "", 204

    async def action_archive_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ReportSnapshotArchiveValidation,
    ) -> tuple[dict[str, Any], int]:
        """Archive a report snapshot."""
        _ = tenant_id
        _ = entity_id

        expected_row_version = int(data.row_version)

        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "archived":
            return "", 204

        now = self._now_utc()

        await self._update_snapshot_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "archived",
                "archived_at": now,
                "archived_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.note),
            },
        )

        return "", 204
