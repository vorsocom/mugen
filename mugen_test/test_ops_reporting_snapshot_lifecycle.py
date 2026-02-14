"""Unit tests for ops_reporting report snapshot generation and lifecycle actions."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.ops_reporting.api.validation import (
    ReportSnapshotArchiveValidation,
    ReportSnapshotGenerateValidation,
    ReportSnapshotPublishValidation,
)
from mugen.core.plugin.ops_reporting.domain import (
    MetricDefinitionDE,
    MetricSeriesDE,
    ReportDefinitionDE,
    ReportSnapshotDE,
)
from mugen.core.plugin.ops_reporting.service.report_snapshot import (
    ReportSnapshotService,
)


class TestOpsReportingSnapshotLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests snapshot generation + publish/archive lifecycle transitions."""

    async def test_generate_then_publish_then_archive_snapshot(self) -> None:
        tenant_id = uuid.uuid4()
        snapshot_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = ReportSnapshotService(table="ops_reporting_report_snapshot", rsg=Mock())

        current = ReportSnapshotDE(
            id=snapshot_id,
            tenant_id=tenant_id,
            report_definition_id=uuid.uuid4(),
            status="draft",
            row_version=3,
            window_start=datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 2, 14, 11, 0, tzinfo=timezone.utc),
            scope_key="__all__",
        )

        svc._get_for_action = AsyncMock(return_value=current)
        svc._report_definition_service.get = AsyncMock(
            return_value=ReportDefinitionDE(
                id=current.report_definition_id,
                tenant_id=tenant_id,
                metric_codes=["tickets_open", "tickets_closed"],
            )
        )

        def _metric_lookup(where):
            if where["code"] == "tickets_open":
                return MetricDefinitionDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    code="tickets_open",
                    name="Tickets Open",
                )

            return MetricDefinitionDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                code="tickets_closed",
                name="Tickets Closed",
            )

        svc._metric_definition_service.get = AsyncMock(side_effect=_metric_lookup)
        svc._metric_series_service.list = AsyncMock(
            side_effect=[
                [MetricSeriesDE(value_numeric=11, source_count=11)],
                [MetricSeriesDE(value_numeric=7, source_count=7)],
            ]
        )

        svc._update_snapshot_with_row_version = AsyncMock(return_value=current)

        generate_result = await svc.action_generate_snapshot(
            tenant_id=tenant_id,
            entity_id=snapshot_id,
            where={"tenant_id": tenant_id, "id": snapshot_id},
            auth_user_id=actor_id,
            data=ReportSnapshotGenerateValidation(row_version=3),
        )

        self.assertEqual(generate_result, ("", 204))
        generate_changes = (
            svc._update_snapshot_with_row_version.await_args.kwargs["changes"]
        )
        self.assertEqual(generate_changes["status"], "generated")
        self.assertEqual(
            generate_changes["metric_codes"],
            ["tickets_open", "tickets_closed"],
        )
        self.assertEqual(generate_changes["summary_json"]["metric_count"], 2)

        generated = ReportSnapshotDE(
            id=snapshot_id,
            tenant_id=tenant_id,
            status="generated",
            row_version=4,
        )
        svc._get_for_action = AsyncMock(return_value=generated)
        svc._update_snapshot_with_row_version = AsyncMock(return_value=generated)

        publish_result = await svc.action_publish_snapshot(
            tenant_id=tenant_id,
            entity_id=snapshot_id,
            where={"tenant_id": tenant_id, "id": snapshot_id},
            auth_user_id=actor_id,
            data=ReportSnapshotPublishValidation(row_version=4),
        )

        self.assertEqual(publish_result, ("", 204))
        publish_changes = (
            svc._update_snapshot_with_row_version.await_args.kwargs["changes"]
        )
        self.assertEqual(publish_changes["status"], "published")
        self.assertEqual(publish_changes["published_by_user_id"], actor_id)

        published = ReportSnapshotDE(
            id=snapshot_id,
            tenant_id=tenant_id,
            status="published",
            row_version=5,
        )
        svc._get_for_action = AsyncMock(return_value=published)
        svc._update_snapshot_with_row_version = AsyncMock(return_value=published)

        archive_result = await svc.action_archive_snapshot(
            tenant_id=tenant_id,
            entity_id=snapshot_id,
            where={"tenant_id": tenant_id, "id": snapshot_id},
            auth_user_id=actor_id,
            data=ReportSnapshotArchiveValidation(row_version=5),
        )

        self.assertEqual(archive_result, ("", 204))
        archive_changes = (
            svc._update_snapshot_with_row_version.await_args.kwargs["changes"]
        )
        self.assertEqual(archive_changes["status"], "archived")
        self.assertEqual(archive_changes["archived_by_user_id"], actor_id)
