"""Branch coverage tests for ops_reporting ReportSnapshotService."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
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
from mugen.core.plugin.ops_reporting.service import report_snapshot as snapshot_mod
from mugen.core.plugin.ops_reporting.service.report_snapshot import (
    ReportSnapshotService,
)


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _snapshot(
    *,
    snapshot_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    report_definition_id: uuid.UUID | None = None,
    status: str = "draft",
    row_version: int = 1,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    scope_key: str | None = "__all__",
    metric_codes: list[str] | None = None,
) -> ReportSnapshotDE:
    return ReportSnapshotDE(
        id=snapshot_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        report_definition_id=report_definition_id,
        status=status,
        row_version=row_version,
        window_start=window_start,
        window_end=window_end,
        scope_key=scope_key,
        metric_codes=metric_codes,
    )


class TestMugenOpsReportingReportSnapshotService(unittest.IsolatedAsyncioTestCase):
    """Covers static helpers, branch-heavy helper methods, and action guards."""

    def test_static_helper_branches(self) -> None:
        naive = datetime(2026, 2, 14, 9, 0)
        aware = datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(
            ReportSnapshotService._to_aware_utc(naive).tzinfo,
            timezone.utc,
        )
        self.assertEqual(
            ReportSnapshotService._to_aware_utc(aware).tzinfo,
            timezone.utc,
        )

        self.assertEqual(ReportSnapshotService._normalize_scope_key(None), "__all__")
        self.assertEqual(ReportSnapshotService._normalize_scope_key("  "), "__all__")
        self.assertEqual(ReportSnapshotService._normalize_scope_key(" team "), "team")

        self.assertIsNone(ReportSnapshotService._normalize_optional_text(None))
        self.assertIsNone(ReportSnapshotService._normalize_optional_text("   "))
        self.assertEqual(
            ReportSnapshotService._normalize_optional_text(" hello "),
            "hello",
        )

        self.assertEqual(ReportSnapshotService._normalize_metric_codes("x"), [])
        self.assertEqual(
            ReportSnapshotService._normalize_metric_codes([" a ", "", "a", "b"]),
            ["a", "b"],
        )

    async def test_create_normalizes_payload(self) -> None:
        tenant_id = uuid.uuid4()
        report_definition_id = uuid.uuid4()
        snapshot_id = uuid.uuid4()

        rsg = Mock()
        rsg.insert_one = AsyncMock(
            return_value={
                "id": snapshot_id,
                "tenant_id": tenant_id,
                "report_definition_id": report_definition_id,
                "status": "draft",
                "scope_key": "__all__",
                "metric_codes": ["alpha", "beta"],
                "note": None,
            }
        )
        svc = ReportSnapshotService(table="ops_reporting_report_snapshot", rsg=rsg)

        created = await svc.create(
            {
                "tenant_id": tenant_id,
                "report_definition_id": report_definition_id,
                "scope_key": " ",
                "metric_codes": [" alpha ", "", "beta", "alpha"],
                "status": "",
                "note": "   ",
            }
        )

        payload = rsg.insert_one.await_args.args[1]
        self.assertEqual(payload["scope_key"], "__all__")
        self.assertEqual(payload["metric_codes"], ["alpha", "beta"])
        self.assertEqual(payload["status"], "draft")
        self.assertIsNone(payload["note"])

        self.assertEqual(created.id, snapshot_id)
        self.assertEqual(created.status, "draft")

    async def test_get_for_action_and_update_helper_branches(self) -> None:
        svc = ReportSnapshotService(table="ops_reporting_report_snapshot", rsg=Mock())
        current = _snapshot()
        where = {"id": current.id}

        svc.get = AsyncMock(return_value=current)
        resolved = await svc._get_for_action(where=where, expected_row_version=3)
        self.assertEqual(resolved.id, current.id)

        with patch.object(snapshot_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, None])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(side_effect=[None, current])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=current)
        updated = await svc._update_snapshot_with_row_version(
            where=where,
            expected_row_version=3,
            changes={"status": "generated"},
        )
        self.assertEqual(updated.id, current.id)

        with patch.object(snapshot_mod, "abort", side_effect=_abort_raiser):
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("ops_reporting_report_snapshot", where)
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_snapshot_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={"status": "generated"},
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_snapshot_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={"status": "generated"},
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_snapshot_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={"status": "generated"},
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_resolve_metric_codes_and_window_branches(self) -> None:
        svc = ReportSnapshotService(table="ops_reporting_report_snapshot", rsg=Mock())
        tenant_id = uuid.uuid4()
        report_id = uuid.uuid4()

        direct_codes = await svc._resolve_metric_codes(
            tenant_id=tenant_id,
            snapshot=_snapshot(metric_codes=[" x ", "", "x", "y"]),
        )
        self.assertEqual(direct_codes, ["x", "y"])

        with patch.object(snapshot_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_metric_codes(
                    tenant_id=tenant_id,
                    snapshot=_snapshot(metric_codes=None, report_definition_id=None),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._report_definition_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_metric_codes(
                    tenant_id=tenant_id,
                    snapshot=_snapshot(metric_codes=None, report_definition_id=report_id),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._report_definition_service.get = AsyncMock(
                return_value=ReportDefinitionDE(
                    id=report_id,
                    tenant_id=tenant_id,
                    metric_codes=None,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._resolve_metric_codes(
                    tenant_id=tenant_id,
                    snapshot=_snapshot(metric_codes=None, report_definition_id=report_id),
                )
            self.assertEqual(ex.exception.code, 409)

        svc._report_definition_service.get = AsyncMock(
            return_value=ReportDefinitionDE(
                id=report_id,
                tenant_id=tenant_id,
                metric_codes=[" a ", "", "b", "a"],
            )
        )
        report_codes = await svc._resolve_metric_codes(
            tenant_id=tenant_id,
            snapshot=_snapshot(metric_codes=None, report_definition_id=report_id),
        )
        self.assertEqual(report_codes, ["a", "b"])

        aware_start = datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc)
        aware_end = datetime(2026, 2, 14, 11, 0, tzinfo=timezone.utc)
        start, end = svc._resolve_window(
            snapshot=_snapshot(window_start=aware_start, window_end=aware_end),
            data=ReportSnapshotGenerateValidation(row_version=1),
        )
        self.assertEqual(start, aware_start)
        self.assertEqual(end, aware_end)

        naive_start = datetime(2026, 2, 14, 12, 0)
        naive_end = datetime(2026, 2, 14, 13, 0)
        start, end = svc._resolve_window(
            snapshot=_snapshot(),
            data=SimpleNamespace(window_start=naive_start, window_end=naive_end),
        )
        self.assertEqual(start.tzinfo, timezone.utc)
        self.assertEqual(end.tzinfo, timezone.utc)

        with patch.object(snapshot_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                svc._resolve_window(
                    snapshot=_snapshot(window_start=None, window_end=None),
                    data=SimpleNamespace(window_start=None, window_end=None),
                )
            self.assertEqual(ex.exception.code, 409)

            with self.assertRaises(_AbortCalled) as ex:
                svc._resolve_window(
                    snapshot=_snapshot(),
                    data=SimpleNamespace(window_start=aware_start, window_end=aware_start),
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_build_metric_summary_covers_missing_and_present_branches(self) -> None:
        tenant_id = uuid.uuid4()
        metric_id = uuid.uuid4()
        start = datetime(2026, 2, 14, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 14, 1, 0, tzinfo=timezone.utc)

        svc = ReportSnapshotService(table="ops_reporting_report_snapshot", rsg=Mock())
        svc._metric_definition_service.get = AsyncMock(
            side_effect=[
                None,
                MetricDefinitionDE(
                    id=metric_id,
                    tenant_id=tenant_id,
                    code="resolved",
                    name="Resolved Metric",
                ),
            ]
        )
        svc._metric_series_service.list = AsyncMock(
            return_value=[
                MetricSeriesDE(
                    value_numeric=2,
                    source_count=3,
                    computed_at=datetime(2026, 2, 14, 0, 30, tzinfo=timezone.utc),
                ),
                MetricSeriesDE(
                    value_numeric=5,
                    source_count=7,
                    computed_at=datetime(2026, 2, 14, 0, 45, tzinfo=timezone.utc),
                ),
            ]
        )

        summary = await svc._build_metric_summary(
            tenant_id=tenant_id,
            metric_codes=["missing", "resolved"],
            window_start=start,
            window_end=end,
            scope_key="ops",
        )

        self.assertEqual(len(summary), 2)
        self.assertTrue(summary[0]["missing_metric_definition"])
        self.assertEqual(summary[0]["value_numeric"], 0)

        self.assertFalse(summary[1]["missing_metric_definition"])
        self.assertEqual(summary[1]["bucket_count"], 2)
        self.assertEqual(summary[1]["source_count"], 10)
        self.assertEqual(summary[1]["value_numeric"], 7)
        self.assertEqual(
            summary[1]["last_computed_at"],
            datetime(2026, 2, 14, 0, 45, tzinfo=timezone.utc).isoformat(),
        )

        filter_group = svc._metric_series_service.list.await_args.kwargs["filter_groups"][
            0
        ]
        self.assertEqual(filter_group.where["metric_definition_id"], metric_id)
        self.assertEqual(filter_group.scalar_filters[0].value, start)
        self.assertEqual(filter_group.scalar_filters[1].value, end)

    async def test_action_branches_for_generate_publish_and_archive(self) -> None:
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": entity_id}
        now = datetime(2026, 2, 14, 16, 0, tzinfo=timezone.utc)

        svc = ReportSnapshotService(table="ops_reporting_report_snapshot", rsg=Mock())
        svc._now_utc = Mock(return_value=now)

        with patch.object(snapshot_mod, "abort", side_effect=_abort_raiser):
            svc._get_for_action = AsyncMock(
                return_value=_snapshot(status="archived", row_version=3)
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_generate_snapshot(
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=ReportSnapshotGenerateValidation(row_version=3),
                )
            self.assertEqual(ex.exception.code, 409)

        current = _snapshot(
            status="draft",
            row_version=3,
            window_start=datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 2, 14, 13, 0, tzinfo=timezone.utc),
            scope_key="__all__",
        )
        svc._get_for_action = AsyncMock(return_value=current)
        svc._resolve_metric_codes = AsyncMock(return_value=["m1"])
        svc._resolve_window = Mock(return_value=(current.window_start, current.window_end))
        svc._build_metric_summary = AsyncMock(return_value=[{"metric_code": "m1"}])
        svc._update_snapshot_with_row_version = AsyncMock(return_value=current)

        generate_result = await svc.action_generate_snapshot(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where=where,
            auth_user_id=actor_id,
            data=ReportSnapshotGenerateValidation(row_version=3, note="  "),
        )
        self.assertEqual(generate_result, ("", 204))
        generate_changes = svc._update_snapshot_with_row_version.await_args.kwargs[
            "changes"
        ]
        self.assertEqual(generate_changes["status"], "generated")
        self.assertEqual(generate_changes["generated_by_user_id"], actor_id)
        self.assertEqual(generate_changes["metric_codes"], ["m1"])
        self.assertEqual(generate_changes["summary_json"]["generated_at"], now.isoformat())
        self.assertIsNone(generate_changes["note"])

        with patch.object(snapshot_mod, "abort", side_effect=_abort_raiser):
            svc._get_for_action = AsyncMock(
                return_value=_snapshot(status="archived", row_version=4)
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_publish_snapshot(
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=ReportSnapshotPublishValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_snapshot(status="draft", row_version=4)
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_publish_snapshot(
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=ReportSnapshotPublishValidation(row_version=4),
                )
            self.assertEqual(ex.exception.code, 409)

        svc._get_for_action = AsyncMock(return_value=_snapshot(status="published", row_version=4))
        svc._update_snapshot_with_row_version = AsyncMock()
        self.assertEqual(
            await svc.action_publish_snapshot(
                tenant_id=tenant_id,
                entity_id=entity_id,
                where=where,
                auth_user_id=actor_id,
                data=ReportSnapshotPublishValidation(row_version=4),
            ),
            ("", 204),
        )
        svc._update_snapshot_with_row_version.assert_not_awaited()

        svc._get_for_action = AsyncMock(return_value=_snapshot(status="generated", row_version=4))
        svc._update_snapshot_with_row_version = AsyncMock()
        self.assertEqual(
            await svc.action_publish_snapshot(
                tenant_id=tenant_id,
                entity_id=entity_id,
                where=where,
                auth_user_id=actor_id,
                data=ReportSnapshotPublishValidation(row_version=4, note="  "),
            ),
            ("", 204),
        )
        publish_changes = svc._update_snapshot_with_row_version.await_args.kwargs[
            "changes"
        ]
        self.assertEqual(publish_changes["status"], "published")
        self.assertEqual(publish_changes["published_at"], now)
        self.assertEqual(publish_changes["published_by_user_id"], actor_id)
        self.assertIsNone(publish_changes["note"])

        svc._get_for_action = AsyncMock(return_value=_snapshot(status="archived", row_version=5))
        svc._update_snapshot_with_row_version = AsyncMock()
        self.assertEqual(
            await svc.action_archive_snapshot(
                tenant_id=tenant_id,
                entity_id=entity_id,
                where=where,
                auth_user_id=actor_id,
                data=ReportSnapshotArchiveValidation(row_version=5),
            ),
            ("", 204),
        )
        svc._update_snapshot_with_row_version.assert_not_awaited()

        svc._get_for_action = AsyncMock(return_value=_snapshot(status="published", row_version=5))
        svc._update_snapshot_with_row_version = AsyncMock()
        self.assertEqual(
            await svc.action_archive_snapshot(
                tenant_id=tenant_id,
                entity_id=entity_id,
                where=where,
                auth_user_id=actor_id,
                data=ReportSnapshotArchiveValidation(row_version=5, note="  "),
            ),
            ("", 204),
        )
        archive_changes = svc._update_snapshot_with_row_version.await_args.kwargs[
            "changes"
        ]
        self.assertEqual(archive_changes["status"], "archived")
        self.assertEqual(archive_changes["archived_at"], now)
        self.assertEqual(archive_changes["archived_by_user_id"], actor_id)
        self.assertIsNone(archive_changes["note"])
