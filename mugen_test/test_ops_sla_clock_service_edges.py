"""Unit tests for ops_sla SlaClockService edge and guard branches."""

from datetime import datetime, time, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_sla.api.validation import (
    SlaClockMarkBreachedValidation,
    SlaClockResumeValidation,
    SlaClockStartValidation,
    SlaClockStopValidation,
    SlaClockTickValidation,
)
from mugen.core.plugin.ops_sla.domain import (
    SlaCalendarDE,
    SlaClockDE,
    SlaClockDefinitionDE,
    SlaPolicyDE,
    SlaTargetDE,
)
from mugen.core.plugin.ops_sla.service.sla_clock import SlaClockService


class TestSlaClockServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Covers helper and action branches not exercised by lifecycle tests."""

    def _svc(self) -> SlaClockService:
        return SlaClockService(table="ops_sla_clock", rsg=Mock())

    def test_now_utc_returns_timezone_aware_datetime(self) -> None:
        now = SlaClockService._now_utc()
        self.assertIsNotNone(now.tzinfo)

    def test_to_aware_utc_handles_naive_and_aware_values(self) -> None:
        naive = datetime(2026, 2, 14, 12, 0)
        aware = datetime(2026, 2, 14, 12, 0, tzinfo=timezone(timedelta(hours=-5)))

        self.assertEqual(
            SlaClockService._to_aware_utc(naive),
            datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            SlaClockService._to_aware_utc(aware),
            datetime(2026, 2, 14, 17, 0, tzinfo=timezone.utc),
        )

    def test_holiday_dates_ignores_non_strings_and_invalid_dates(self) -> None:
        out = SlaClockService._holiday_dates(
            [
                "2026-02-14",
                "not-a-date",
                5,  # type: ignore[list-item]
            ]
        )
        self.assertEqual(out, {datetime(2026, 2, 14, tzinfo=timezone.utc).date()})

    def test_add_business_seconds_handles_early_return_and_invalid_timezone(
        self,
    ) -> None:
        svc = self._svc()
        start = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        calendar = SlaCalendarDE(timezone="UTC")

        self.assertEqual(
            svc._add_business_seconds(start_at=start, seconds=0, calendar=calendar),
            start,
        )

        invalid_tz_calendar = SlaCalendarDE(timezone="bad/timezone")
        self.assertEqual(
            svc._add_business_seconds(
                start_at=start,
                seconds=90,
                calendar=invalid_tz_calendar,
            ),
            start + timedelta(seconds=90),
        )

    def test_add_business_seconds_alignment_and_subsecond_day_end(self) -> None:
        svc = self._svc()
        calendar = SlaCalendarDE(
            timezone="UTC",
            business_start_time=time(9, 0),
            business_end_time=time(17, 0),
            business_days=[1, 2, 3, 4, 5],
            holiday_refs=[],
        )

        before_open = datetime(2026, 2, 16, 8, 30, tzinfo=timezone.utc)  # Monday
        self.assertEqual(
            svc._add_business_seconds(
                start_at=before_open,
                seconds=120,
                calendar=calendar,
            ),
            datetime(2026, 2, 16, 9, 2, tzinfo=timezone.utc),
        )

        near_close = datetime(2026, 2, 16, 16, 59, 59, 900000, tzinfo=timezone.utc)
        self.assertEqual(
            svc._add_business_seconds(
                start_at=near_close,
                seconds=1,
                calendar=calendar,
            ),
            datetime(2026, 2, 17, 9, 0, 1, tzinfo=timezone.utc),
        )

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
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=2)
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            side_effect=[None, SlaClockDE(id=where["id"], tenant_id=where["tenant_id"])]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=2)
        self.assertEqual(ctx.exception.code, 409)

    async def test_get_for_action_raises_500_when_base_lookup_fails(self) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])

        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(where=where, expected_row_version=3)

        self.assertEqual(ctx.exception.code, 500)

    async def test_update_clock_with_row_version_raises_for_conflict_sql_and_none(
        self,
    ) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_sla_clock")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_clock_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "running"},
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_clock_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "running"},
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_clock_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "running"},
            )
        self.assertEqual(ctx.exception.code, 404)

    async def test_resolve_policy_none_and_lookup_paths(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()

        self.assertIsNone(
            await svc._resolve_policy(tenant_id=tenant_id, policy_id=None)
        )

        policy = SlaPolicyDE(id=uuid.uuid4(), tenant_id=tenant_id)
        svc._policy_service.get = AsyncMock(return_value=policy)
        out = await svc._resolve_policy(tenant_id=tenant_id, policy_id=policy.id)
        self.assertIs(out, policy)

    async def test_resolve_calendar_uses_clock_id_then_policy_fallback(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        explicit_calendar = SlaCalendarDE(id=uuid.uuid4(), tenant_id=tenant_id)
        fallback_calendar = SlaCalendarDE(id=uuid.uuid4(), tenant_id=tenant_id)

        clock_with_calendar = SlaClockDE(calendar_id=uuid.uuid4())
        svc._calendar_service.get = AsyncMock(return_value=explicit_calendar)
        out = await svc._resolve_calendar(
            tenant_id=tenant_id, clock=clock_with_calendar
        )
        self.assertIs(out, explicit_calendar)

        policy_calendar_id = uuid.uuid4()
        svc._calendar_service.get = AsyncMock(side_effect=[None, fallback_calendar])
        svc._resolve_policy = AsyncMock(
            return_value=SlaPolicyDE(id=uuid.uuid4(), calendar_id=policy_calendar_id)
        )
        out = await svc._resolve_calendar(
            tenant_id=tenant_id, clock=clock_with_calendar
        )
        self.assertIs(out, fallback_calendar)

        clock_without_calendar = SlaClockDE(policy_id=uuid.uuid4())
        svc._resolve_policy = AsyncMock(return_value=SlaPolicyDE(id=uuid.uuid4()))
        svc._calendar_service.get = AsyncMock(return_value=fallback_calendar)
        out = await svc._resolve_calendar(
            tenant_id=tenant_id,
            clock=clock_without_calendar,
        )
        self.assertIsNone(out)

    async def test_resolve_target_uses_explicit_id_then_policy_lookup(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()

        explicit_target = SlaTargetDE(id=uuid.uuid4(), tenant_id=tenant_id)
        clock = SlaClockDE(target_id=uuid.uuid4())
        svc._target_service.get = AsyncMock(return_value=explicit_target)
        out = await svc._resolve_target(tenant_id=tenant_id, clock=clock)
        self.assertIs(out, explicit_target)

        clock = SlaClockDE(target_id=uuid.uuid4(), policy_id=None)
        svc._target_service.get = AsyncMock(return_value=None)
        out = await svc._resolve_target(tenant_id=tenant_id, clock=clock)
        self.assertIsNone(out)

        policy_id = uuid.uuid4()
        fallback_target = SlaTargetDE(id=uuid.uuid4(), policy_id=policy_id)
        clock = SlaClockDE(policy_id=policy_id, metric="response", priority="p1")
        svc._target_service.get = AsyncMock(return_value=fallback_target)
        out = await svc._resolve_target(tenant_id=tenant_id, clock=clock)
        self.assertIs(out, fallback_target)

    def test_elapsed_with_open_segment_handles_naive_and_future_start(self) -> None:
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        naive_running = SlaClockDE(
            status="running",
            elapsed_seconds=5,
            last_started_at=datetime(2026, 2, 14, 11, 59, 50),
        )
        self.assertEqual(
            SlaClockService._elapsed_with_open_segment(naive_running, now),
            15,
        )

        future_running = SlaClockDE(
            status="running",
            elapsed_seconds=7,
            last_started_at=datetime(2026, 2, 14, 12, 0, 1),
        )
        self.assertEqual(
            SlaClockService._elapsed_with_open_segment(future_running, now), 7
        )

    async def test_compute_deadline_handles_all_remaining_time_branches(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        clock = SlaClockDE(metric="response")
        at_time = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)

        svc._resolve_target = AsyncMock(return_value=SlaTargetDE(target_minutes=0))
        self.assertIsNone(
            await svc._compute_deadline(
                tenant_id=tenant_id,
                clock=clock,
                at_time=at_time,
                elapsed_seconds=0,
            )
        )

        svc._resolve_target = AsyncMock(return_value=SlaTargetDE(target_minutes=1))
        self.assertEqual(
            await svc._compute_deadline(
                tenant_id=tenant_id,
                clock=clock,
                at_time=at_time,
                elapsed_seconds=75,
            ),
            at_time,
        )

        svc._resolve_target = AsyncMock(return_value=SlaTargetDE(target_minutes=2))
        svc._resolve_calendar = AsyncMock(return_value=None)
        self.assertEqual(
            await svc._compute_deadline(
                tenant_id=tenant_id,
                clock=clock,
                at_time=at_time,
                elapsed_seconds=0,
            ),
            at_time + timedelta(seconds=120),
        )

        expected = datetime(2026, 2, 14, 13, 0, tzinfo=timezone.utc)
        svc._resolve_target = AsyncMock(return_value=SlaTargetDE(target_minutes=3))
        svc._resolve_calendar = AsyncMock(return_value=SlaCalendarDE(timezone="UTC"))
        svc._add_business_seconds = Mock(return_value=expected)
        self.assertEqual(
            await svc._compute_deadline(
                tenant_id=tenant_id,
                clock=clock,
                at_time=at_time,
                elapsed_seconds=30,
            ),
            expected,
        )

    async def test_action_start_clock_rejects_already_running_status(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        svc.get = AsyncMock(
            return_value=SlaClockDE(
                id=clock_id,
                tenant_id=tenant_id,
                status="running",
                row_version=1,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_start_clock(
                tenant_id=tenant_id,
                entity_id=clock_id,
                where={"tenant_id": tenant_id, "id": clock_id},
                auth_user_id=uuid.uuid4(),
                data=SlaClockStartValidation(row_version=1),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_action_resume_clock_rejects_non_paused_status(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        svc.get = AsyncMock(
            return_value=SlaClockDE(
                id=clock_id,
                tenant_id=tenant_id,
                status="idle",
                row_version=2,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_resume_clock(
                tenant_id=tenant_id,
                entity_id=clock_id,
                where={"tenant_id": tenant_id, "id": clock_id},
                auth_user_id=uuid.uuid4(),
                data=SlaClockResumeValidation(row_version=2),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_action_stop_clock_rejects_invalid_status(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        svc.get = AsyncMock(
            return_value=SlaClockDE(
                id=clock_id,
                tenant_id=tenant_id,
                status="idle",
                row_version=3,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_stop_clock(
                tenant_id=tenant_id,
                entity_id=clock_id,
                where={"tenant_id": tenant_id, "id": clock_id},
                auth_user_id=uuid.uuid4(),
                data=SlaClockStopValidation(row_version=3),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_warn_offsets_and_best_effort_update_clock_branches(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()

        self.assertEqual(
            SlaClockService._warn_offsets([60, "120", 0, -1, "bad"]), {60, 120}
        )

        expected = SlaClockDE(id=clock_id, tenant_id=tenant_id, status="running")
        svc.update_with_row_version = AsyncMock(return_value=expected)
        updated = await svc._best_effort_update_clock(
            where={"tenant_id": tenant_id, "id": clock_id},
            expected_row_version=2,
            changes={"status": "running"},
        )
        self.assertEqual(updated.id, clock_id)

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_sla_clock")
        )
        self.assertIsNone(
            await svc._best_effort_update_clock(
                where={"tenant_id": tenant_id, "id": clock_id},
                expected_row_version=2,
                changes={"status": "running"},
            )
        )

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._best_effort_update_clock(
                where={"tenant_id": tenant_id, "id": clock_id},
                expected_row_version=2,
                changes={"status": "running"},
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_resolve_clock_definition_and_target_context_branches(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        definition_id = uuid.uuid4()

        definition = SlaClockDefinitionDE(
            id=definition_id,
            tenant_id=tenant_id,
            target_minutes=10,
            warn_offsets_json=[300, "60"],
        )
        svc._clock_definition_service.get = AsyncMock(return_value=definition)
        resolved = await svc._resolve_clock_definition(
            tenant_id=tenant_id,
            clock_definition_id=definition_id,
        )
        self.assertEqual(resolved.id, definition_id)

        svc._resolve_clock_definition = AsyncMock(return_value=definition)
        svc._resolve_target = AsyncMock(return_value=None)
        clock = SlaClockDE(clock_definition_id=definition_id)
        target_minutes, warn_offsets, returned_definition = (
            await svc._resolve_target_context(
                tenant_id=tenant_id,
                clock=clock,
            )
        )
        self.assertEqual(target_minutes, 10)
        self.assertEqual(warn_offsets, {60, 300})
        self.assertEqual(returned_definition.id, definition_id)

        zero_definition = SlaClockDefinitionDE(
            id=definition_id,
            tenant_id=tenant_id,
            target_minutes=0,
        )
        svc._resolve_clock_definition = AsyncMock(return_value=zero_definition)
        svc._resolve_target = AsyncMock(
            return_value=SlaTargetDE(target_minutes=20, warn_before_minutes=3)
        )
        target_minutes, warn_offsets, returned_definition = (
            await svc._resolve_target_context(
                tenant_id=tenant_id,
                clock=SlaClockDE(policy_id=uuid.uuid4(), metric="response"),
            )
        )
        self.assertEqual(target_minutes, 20)
        self.assertEqual(warn_offsets, {180})
        self.assertEqual(returned_definition.id, definition_id)

        svc._resolve_target = AsyncMock(return_value=None)
        target_minutes, warn_offsets, _ = await svc._resolve_target_context(
            tenant_id=tenant_id,
            clock=SlaClockDE(policy_id=uuid.uuid4(), metric="response"),
        )
        self.assertEqual((target_minutes, warn_offsets), (0, set()))

    async def test_action_mark_breached_skips_clock_event_when_id_missing(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        now = datetime(2026, 2, 16, 12, 0, tzinfo=timezone.utc)
        svc._now_utc = lambda: now

        current = SlaClockDE(
            id=None,
            tenant_id=tenant_id,
            status="paused",
            row_version=2,
            elapsed_seconds=15,
            metric="response",
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._append_breach_event = AsyncMock(return_value=Mock())
        svc._resolve_clock_definition = AsyncMock(return_value=None)
        svc._append_clock_event = AsyncMock()

        result = await svc.action_mark_breached(
            tenant_id=tenant_id,
            entity_id=uuid.uuid4(),
            where={"tenant_id": tenant_id, "id": uuid.uuid4()},
            auth_user_id=actor_id,
            data=SlaClockMarkBreachedValidation(row_version=2, event_type="breached"),
        )
        self.assertEqual(result, ("", 204))
        svc._append_clock_event.assert_not_awaited()

    async def test_action_tick_dry_run_warn_and_breach_rows(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        now = datetime(2026, 2, 16, 12, 30, tzinfo=timezone.utc)

        idless_clock = SlaClockDE(
            id=None,
            tenant_id=tenant_id,
            status="running",
            row_version=1,
            elapsed_seconds=0,
        )
        warn_clock = SlaClockDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            status="running",
            row_version=2,
            elapsed_seconds=10,
            trace_id="trace-warn",
            warned_offsets_json=[],
            is_breached=False,
        )
        breach_clock = SlaClockDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            status="running",
            row_version=3,
            elapsed_seconds=10,
            trace_id="trace-breach",
            warned_offsets_json=[],
            is_breached=False,
        )

        svc.list = AsyncMock(return_value=[idless_clock, warn_clock, breach_clock])
        svc._compute_deadline = AsyncMock(
            side_effect=[now + timedelta(seconds=30), now - timedelta(seconds=1)]
        )
        svc._resolve_target_context = AsyncMock(
            side_effect=[(5, {60}, None), (5, set(), None)]
        )

        payload, status = await svc.action_tick(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaClockTickValidation(now_utc=now, dry_run=True),
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["DryRun"])
        self.assertEqual(payload["Counters"]["Scanned"], 3)
        self.assertEqual(payload["Counters"]["WarnedCount"], 1)
        self.assertEqual(payload["Counters"]["BreachedCount"], 1)
        self.assertEqual(payload["Counters"]["ConflictCount"], 0)
        self.assertEqual(payload["Warned"][0]["ClockEventId"], None)
        self.assertEqual(payload["Breached"][0]["ClockEventId"], None)

    async def test_action_tick_persist_paths_with_conflict_warn_and_breach(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        now = datetime(2026, 2, 16, 12, 45, tzinfo=timezone.utc)

        warn_id = uuid.uuid4()
        breach_id = uuid.uuid4()
        conflict_id = uuid.uuid4()
        warn_clock = SlaClockDE(
            id=warn_id,
            tenant_id=tenant_id,
            status="running",
            row_version=2,
            elapsed_seconds=10,
            trace_id="trace-warn",
            warned_offsets_json=[],
            is_breached=False,
        )
        breach_clock = SlaClockDE(
            id=breach_id,
            tenant_id=tenant_id,
            status="running",
            row_version=3,
            elapsed_seconds=10,
            trace_id="trace-breach",
            warned_offsets_json=[],
            is_breached=False,
        )
        conflict_clock = SlaClockDE(
            id=conflict_id,
            tenant_id=tenant_id,
            status="running",
            row_version=4,
            elapsed_seconds=10,
            trace_id="trace-conflict",
            warned_offsets_json=[],
            is_breached=False,
        )

        svc.list = AsyncMock(return_value=[warn_clock, breach_clock, conflict_clock])
        svc._compute_deadline = AsyncMock(
            side_effect=[
                now + timedelta(seconds=30),
                now - timedelta(seconds=1),
                now + timedelta(seconds=10),
            ]
        )
        svc._resolve_target_context = AsyncMock(
            side_effect=[(5, {60}, None), (5, set(), None), (5, {20}, None)]
        )
        updated_warn = SlaClockDE(
            id=warn_id,
            tenant_id=tenant_id,
            status="running",
            row_version=3,
            trace_id="trace-warn",
            warned_offsets_json=[60],
            is_breached=False,
        )
        updated_breach = SlaClockDE(
            id=breach_id,
            tenant_id=tenant_id,
            status="breached",
            row_version=4,
            trace_id="trace-breach",
            warned_offsets_json=[],
            is_breached=True,
        )
        svc._best_effort_update_clock = AsyncMock(
            side_effect=[updated_warn, updated_breach, None]
        )
        warn_event_id = uuid.uuid4()
        breach_event_id = uuid.uuid4()
        svc._append_clock_event = AsyncMock(
            side_effect=[Mock(id=warn_event_id), Mock(id=breach_event_id)]
        )

        payload, status = await svc.action_tick(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaClockTickValidation(now_utc=now, dry_run=False),
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["DryRun"])
        self.assertEqual(payload["Counters"]["Scanned"], 3)
        self.assertEqual(payload["Counters"]["WarnedCount"], 1)
        self.assertEqual(payload["Counters"]["BreachedCount"], 1)
        self.assertEqual(payload["Counters"]["ConflictCount"], 1)
        self.assertEqual(payload["Warned"][0]["ClockEventId"], str(warn_event_id))
        self.assertEqual(payload["Breached"][0]["ClockEventId"], str(breach_event_id))

    async def test_action_tick_skips_rows_when_deadline_unavailable(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        now = datetime(2026, 2, 16, 12, 50, tzinfo=timezone.utc)

        clock = SlaClockDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            status="running",
            row_version=2,
            elapsed_seconds=10,
            warned_offsets_json=[],
            is_breached=False,
        )

        svc.list = AsyncMock(return_value=[clock])
        svc._compute_deadline = AsyncMock(return_value=None)
        svc._resolve_target_context = AsyncMock(return_value=(5, {60}, None))

        payload, status = await svc.action_tick(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaClockTickValidation(now_utc=now, dry_run=True),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["Counters"]["Scanned"], 1)
        self.assertEqual(payload["Counters"]["WarnedCount"], 0)
        self.assertEqual(payload["Counters"]["BreachedCount"], 0)
