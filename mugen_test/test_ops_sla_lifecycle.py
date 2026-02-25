"""Unit tests for ops_sla clock lifecycle and breach behavior."""

from datetime import datetime, time, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.ops_sla.api.validation import (
    SlaClockMarkBreachedValidation,
    SlaClockPauseValidation,
    SlaClockResumeValidation,
    SlaClockStartValidation,
    SlaClockStopValidation,
    SlaClockTickValidation,
)
from mugen.core.plugin.ops_sla.domain import SlaCalendarDE, SlaClockDE
from mugen.core.plugin.ops_sla.service.sla_clock import SlaClockService


class TestOpsSlaLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests SLA clock lifecycle transitions on SlaClockService."""

    async def test_start_clock_sets_running_state(self) -> None:
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = SlaClockService(table="ops_sla_clock", rsg=Mock())
        now = datetime(2026, 2, 13, 16, 0, tzinfo=timezone.utc)

        svc._now_utc = lambda: now

        current = SlaClockDE(
            id=clock_id,
            tenant_id=tenant_id,
            status="idle",
            row_version=2,
            elapsed_seconds=0,
            metric="response",
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)

        result = await svc.action_start_clock(
            tenant_id=tenant_id,
            entity_id=clock_id,
            where={"tenant_id": tenant_id, "id": clock_id},
            auth_user_id=actor_id,
            data=SlaClockStartValidation(row_version=2),
        )

        self.assertEqual(result, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "running")
        self.assertEqual(changes["last_started_at"], now)
        self.assertEqual(changes["last_actor_user_id"], actor_id)

    async def test_pause_then_resume_then_stop_updates_elapsed(self) -> None:
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = SlaClockService(table="ops_sla_clock", rsg=Mock())

        pause_now = datetime(2026, 2, 13, 16, 2, tzinfo=timezone.utc)
        resume_now = datetime(2026, 2, 13, 16, 10, tzinfo=timezone.utc)
        stop_now = datetime(2026, 2, 13, 16, 15, tzinfo=timezone.utc)

        # pause (running -> paused)
        running = SlaClockDE(
            id=clock_id,
            tenant_id=tenant_id,
            status="running",
            row_version=4,
            elapsed_seconds=30,
            last_started_at=datetime(2026, 2, 13, 16, 0, tzinfo=timezone.utc),
            metric="response",
        )
        svc._now_utc = lambda: pause_now
        svc.get = AsyncMock(return_value=running)
        svc.update_with_row_version = AsyncMock(return_value=running)

        pause_result = await svc.action_pause_clock(
            tenant_id=tenant_id,
            entity_id=clock_id,
            where={"tenant_id": tenant_id, "id": clock_id},
            auth_user_id=actor_id,
            data=SlaClockPauseValidation(row_version=4),
        )

        self.assertEqual(pause_result, ("", 204))
        pause_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(pause_changes["status"], "paused")
        self.assertEqual(pause_changes["elapsed_seconds"], 150)

        # resume (paused -> running)
        paused = SlaClockDE(
            id=clock_id,
            tenant_id=tenant_id,
            status="paused",
            row_version=5,
            elapsed_seconds=150,
            metric="response",
        )
        svc._now_utc = lambda: resume_now
        svc.get = AsyncMock(return_value=paused)
        svc.update_with_row_version = AsyncMock(return_value=paused)

        resume_result = await svc.action_resume_clock(
            tenant_id=tenant_id,
            entity_id=clock_id,
            where={"tenant_id": tenant_id, "id": clock_id},
            auth_user_id=actor_id,
            data=SlaClockResumeValidation(row_version=5),
        )

        self.assertEqual(resume_result, ("", 204))
        resume_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(resume_changes["status"], "running")
        self.assertEqual(resume_changes["last_started_at"], resume_now)

        # stop (running -> stopped)
        resumed_running = SlaClockDE(
            id=clock_id,
            tenant_id=tenant_id,
            status="running",
            row_version=6,
            elapsed_seconds=150,
            last_started_at=resume_now,
            metric="response",
        )
        svc._now_utc = lambda: stop_now
        svc.get = AsyncMock(return_value=resumed_running)
        svc.update_with_row_version = AsyncMock(return_value=resumed_running)

        stop_result = await svc.action_stop_clock(
            tenant_id=tenant_id,
            entity_id=clock_id,
            where={"tenant_id": tenant_id, "id": clock_id},
            auth_user_id=actor_id,
            data=SlaClockStopValidation(row_version=6),
        )

        self.assertEqual(stop_result, ("", 204))
        stop_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(stop_changes["status"], "stopped")
        self.assertEqual(stop_changes["elapsed_seconds"], 450)

    async def test_stop_from_paused_keeps_elapsed_without_calendar_lookup(self) -> None:
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        stop_now = datetime(2026, 2, 13, 16, 30, tzinfo=timezone.utc)

        svc = SlaClockService(table="ops_sla_clock", rsg=Mock())
        svc._now_utc = lambda: stop_now
        svc._resolve_calendar = AsyncMock()
        paused = SlaClockDE(
            id=clock_id,
            tenant_id=tenant_id,
            status="paused",
            row_version=8,
            elapsed_seconds=321,
            metric="response",
        )
        svc.get = AsyncMock(return_value=paused)
        svc.update_with_row_version = AsyncMock(return_value=paused)

        stop_result = await svc.action_stop_clock(
            tenant_id=tenant_id,
            entity_id=clock_id,
            where={"tenant_id": tenant_id, "id": clock_id},
            auth_user_id=actor_id,
            data=SlaClockStopValidation(row_version=8),
        )

        self.assertEqual(stop_result, ("", 204))
        stop_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(stop_changes["elapsed_seconds"], 321)
        svc._resolve_calendar.assert_not_awaited()

    async def test_mark_breached_appends_event(self) -> None:
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = SlaClockService(table="ops_sla_clock", rsg=Mock())
        now = datetime(2026, 2, 13, 16, 20, tzinfo=timezone.utc)
        svc._now_utc = lambda: now

        current = SlaClockDE(
            id=clock_id,
            tenant_id=tenant_id,
            status="paused",
            row_version=7,
            elapsed_seconds=450,
            breach_count=0,
            metric="response",
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._breach_event_service.create = AsyncMock(return_value=Mock())
        svc._clock_event_service.create = AsyncMock(return_value=Mock())

        result = await svc.action_mark_breached(
            tenant_id=tenant_id,
            entity_id=clock_id,
            where={"tenant_id": tenant_id, "id": clock_id},
            auth_user_id=actor_id,
            data=SlaClockMarkBreachedValidation(
                row_version=7,
                event_type="breached",
                reason="deadline exceeded",
            ),
        )

        self.assertEqual(result, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertTrue(changes["is_breached"])
        self.assertEqual(changes["status"], "breached")
        self.assertEqual(changes["breach_count"], 1)

        event_payload = svc._breach_event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "breached")
        self.assertEqual(event_payload["reason"], "deadline exceeded")

    async def test_pause_requires_running_state(self) -> None:
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()

        svc = SlaClockService(table="ops_sla_clock", rsg=Mock())
        svc.get = AsyncMock(
            return_value=SlaClockDE(
                id=clock_id,
                tenant_id=tenant_id,
                status="idle",
                row_version=1,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_pause_clock(
                tenant_id=tenant_id,
                entity_id=clock_id,
                where={"tenant_id": tenant_id, "id": clock_id},
                auth_user_id=uuid.uuid4(),
                data=SlaClockPauseValidation(row_version=1),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_tick_business_hours_elapsed_breach_rolls_to_next_business_day(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = SlaClockService(table="ops_sla_clock", rsg=Mock())
        calendar = SlaCalendarDE(
            timezone="UTC",
            business_start_time=time(9, 0),
            business_end_time=time(17, 0),
            business_days=[1, 2, 3, 4, 5],
            holiday_refs=[],
        )
        clock = SlaClockDE(
            id=clock_id,
            tenant_id=tenant_id,
            status="running",
            row_version=1,
            elapsed_seconds=0,
            last_started_at=datetime(2026, 2, 13, 16, 0, tzinfo=timezone.utc),  # Friday
            warned_offsets_json=[],
            is_breached=False,
            metric="response",
            trace_id="trace-business-window",
        )

        svc.list = AsyncMock(return_value=[clock])
        svc._resolve_calendar = AsyncMock(return_value=calendar)
        svc._resolve_target_context = AsyncMock(return_value=(120, set(), None))

        evening_payload, evening_status = await svc.action_tick(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaClockTickValidation(
                now_utc=datetime(2026, 2, 13, 18, 0, tzinfo=timezone.utc),
                dry_run=True,
            ),
        )
        self.assertEqual(evening_status, 200)
        self.assertEqual(evening_payload["Counters"]["BreachedCount"], 0)

        next_day_payload, next_day_status = await svc.action_tick(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaClockTickValidation(
                now_utc=datetime(2026, 2, 16, 10, 0, tzinfo=timezone.utc),
                dry_run=True,
            ),
        )
        self.assertEqual(next_day_status, 200)
        self.assertEqual(next_day_payload["Counters"]["BreachedCount"], 1)
