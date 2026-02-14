"""Provides a CRUD service for SLA clock lifecycle and deadline transitions."""

__all__ = ["SlaClockService"]

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_sla.api.validation import (
    SlaClockMarkBreachedValidation,
    SlaClockPauseValidation,
    SlaClockResumeValidation,
    SlaClockStartValidation,
    SlaClockStopValidation,
)
from mugen.core.plugin.ops_sla.contract.service.sla_clock import ISlaClockService
from mugen.core.plugin.ops_sla.domain import (
    SlaBreachEventDE,
    SlaCalendarDE,
    SlaClockDE,
    SlaPolicyDE,
    SlaTargetDE,
)
from mugen.core.plugin.ops_sla.service.sla_breach_event import SlaBreachEventService
from mugen.core.plugin.ops_sla.service.sla_calendar import SlaCalendarService
from mugen.core.plugin.ops_sla.service.sla_policy import SlaPolicyService
from mugen.core.plugin.ops_sla.service.sla_target import SlaTargetService


class SlaClockService(
    IRelationalService[SlaClockDE],
    ISlaClockService,
):
    """A CRUD service for SLA clock lifecycle and business-hours deadlines."""

    _POLICY_TABLE = "ops_sla_policy"
    _CALENDAR_TABLE = "ops_sla_calendar"
    _TARGET_TABLE = "ops_sla_target"
    _BREACH_EVENT_TABLE = "ops_sla_breach_event"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaClockDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._policy_service = SlaPolicyService(table=self._POLICY_TABLE, rsg=rsg)
        self._calendar_service = SlaCalendarService(table=self._CALENDAR_TABLE, rsg=rsg)
        self._target_service = SlaTargetService(table=self._TARGET_TABLE, rsg=rsg)
        self._breach_event_service = SlaBreachEventService(
            table=self._BREACH_EVENT_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _to_aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    async def _get_for_action(
        self,
        *,
        where: dict,
        expected_row_version: int,
    ) -> SlaClockDE:
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
            abort(404, "SLA clock not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_clock_with_row_version(
        self,
        *,
        where: dict,
        expected_row_version: int,
        changes: dict,
    ) -> SlaClockDE:
        svc: ICrudServiceWithRowVersion[SlaClockDE] = self

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

    @staticmethod
    def _business_days(value: list[int] | None) -> set[int]:
        out = {
            int(day)
            for day in (value or [1, 2, 3, 4, 5])
            if isinstance(day, int) and 1 <= int(day) <= 7
        }
        return out or {1, 2, 3, 4, 5}

    @staticmethod
    def _holiday_dates(value: list[str] | None) -> set[date]:
        out: set[date] = set()
        for raw in value or []:
            if not isinstance(raw, str):
                continue
            try:
                out.add(date.fromisoformat(raw))
            except ValueError:
                continue
        return out

    def _add_business_seconds(
        self,
        *,
        start_at: datetime,
        seconds: int,
        calendar: SlaCalendarDE,
    ) -> datetime:
        if seconds <= 0:
            return start_at

        timezone_name = (calendar.timezone or "UTC").strip() or "UTC"
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            return start_at + timedelta(seconds=seconds)

        business_start = calendar.business_start_time or time(hour=9)
        business_end = calendar.business_end_time or time(hour=17)
        business_days = self._business_days(calendar.business_days)
        holidays = self._holiday_dates(calendar.holiday_refs)

        cursor = start_at.astimezone(tz)
        remaining = int(seconds)

        while remaining > 0:
            cursor_date = cursor.date()
            day_start = datetime.combine(cursor_date, business_start, tzinfo=tz)
            day_end = datetime.combine(cursor_date, business_end, tzinfo=tz)

            if cursor_date in holidays or cursor.isoweekday() not in business_days:
                cursor = datetime.combine(
                    cursor_date + timedelta(days=1),
                    business_start,
                    tzinfo=tz,
                )
                continue

            if cursor < day_start:
                cursor = day_start

            if cursor >= day_end:
                cursor = datetime.combine(
                    cursor_date + timedelta(days=1),
                    business_start,
                    tzinfo=tz,
                )
                continue

            available = int((day_end - cursor).total_seconds())
            if available <= 0:
                cursor = datetime.combine(
                    cursor_date + timedelta(days=1),
                    business_start,
                    tzinfo=tz,
                )
                continue

            delta = min(available, remaining)
            cursor += timedelta(seconds=delta)
            remaining -= delta

        return cursor.astimezone(timezone.utc)

    async def _resolve_policy(
        self,
        *,
        tenant_id: uuid.UUID,
        policy_id: uuid.UUID | None,
    ) -> SlaPolicyDE | None:
        if policy_id is None:
            return None

        return await self._policy_service.get(
            {
                "tenant_id": tenant_id,
                "id": policy_id,
            }
        )

    async def _resolve_calendar(
        self,
        *,
        tenant_id: uuid.UUID,
        clock: SlaClockDE,
    ) -> SlaCalendarDE | None:
        if clock.calendar_id is not None:
            calendar = await self._calendar_service.get(
                {
                    "tenant_id": tenant_id,
                    "id": clock.calendar_id,
                }
            )
            if calendar is not None:
                return calendar

        policy = await self._resolve_policy(
            tenant_id=tenant_id,
            policy_id=clock.policy_id,
        )
        if policy is None or policy.calendar_id is None:
            return None

        return await self._calendar_service.get(
            {
                "tenant_id": tenant_id,
                "id": policy.calendar_id,
            }
        )

    async def _resolve_target(
        self,
        *,
        tenant_id: uuid.UUID,
        clock: SlaClockDE,
    ) -> SlaTargetDE | None:
        if clock.target_id is not None:
            target = await self._target_service.get(
                {
                    "tenant_id": tenant_id,
                    "id": clock.target_id,
                }
            )
            if target is not None:
                return target

        if clock.policy_id is None:
            return None

        return await self._target_service.get(
            {
                "tenant_id": tenant_id,
                "policy_id": clock.policy_id,
                "metric": clock.metric,
                "priority": clock.priority,
                "severity": clock.severity,
            }
        )

    @staticmethod
    def _elapsed_with_open_segment(clock: SlaClockDE, now: datetime) -> int:
        elapsed = int(clock.elapsed_seconds or 0)

        if clock.status != "running" or clock.last_started_at is None:
            return elapsed

        started_at = clock.last_started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        delta = int((now - started_at).total_seconds())
        if delta > 0:
            elapsed += delta

        return elapsed

    async def _compute_deadline(
        self,
        *,
        tenant_id: uuid.UUID,
        clock: SlaClockDE,
        at_time: datetime,
        elapsed_seconds: int,
    ) -> datetime | None:
        target = await self._resolve_target(tenant_id=tenant_id, clock=clock)
        target_minutes = int(target.target_minutes or 0) if target is not None else 0
        if target_minutes <= 0:
            return None

        remaining_seconds = (target_minutes * 60) - int(elapsed_seconds)
        if remaining_seconds <= 0:
            return at_time

        calendar = await self._resolve_calendar(tenant_id=tenant_id, clock=clock)
        if calendar is None:
            return at_time + timedelta(seconds=remaining_seconds)

        return self._add_business_seconds(
            start_at=at_time,
            seconds=remaining_seconds,
            calendar=calendar,
        )

    async def _append_breach_event(
        self,
        *,
        tenant_id: uuid.UUID,
        clock_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        data: SlaClockMarkBreachedValidation,
        occurred_at: datetime,
    ) -> SlaBreachEventDE:
        return await self._breach_event_service.create(
            {
                "tenant_id": tenant_id,
                "clock_id": clock_id,
                "event_type": data.event_type,
                "occurred_at": occurred_at,
                "actor_user_id": actor_user_id,
                "escalation_level": int(data.escalation_level or 0),
                "reason": self._normalize_optional_text(data.reason),
                "note": self._normalize_optional_text(data.note),
                "payload": dict(data.payload) if data.payload else None,
            }
        )

    async def action_start_clock(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: SlaClockStartValidation,
    ) -> tuple[dict, int]:
        """Start an idle/paused/stopped SLA clock."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "running":
            abort(409, "Clock is already running.")

        now = self._now_utc()
        elapsed = int(current.elapsed_seconds or 0)
        deadline_at = await self._compute_deadline(
            tenant_id=tenant_id,
            clock=current,
            at_time=now,
            elapsed_seconds=elapsed,
        )

        await self._update_clock_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "running",
                "started_at": current.started_at or now,
                "last_started_at": now,
                "paused_at": None,
                "stopped_at": None,
                "deadline_at": deadline_at,
                "last_actor_user_id": auth_user_id,
            },
        )

        return "", 204

    async def action_pause_clock(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: SlaClockPauseValidation,
    ) -> tuple[dict, int]:
        """Pause a running SLA clock and persist elapsed time."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "running":
            abort(409, "Only running clocks can be paused.")

        now = self._now_utc()
        elapsed = self._elapsed_with_open_segment(current, now)
        deadline_at = await self._compute_deadline(
            tenant_id=tenant_id,
            clock=current,
            at_time=now,
            elapsed_seconds=elapsed,
        )

        await self._update_clock_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "paused",
                "elapsed_seconds": elapsed,
                "last_started_at": None,
                "paused_at": now,
                "stopped_at": None,
                "deadline_at": deadline_at,
                "last_actor_user_id": auth_user_id,
            },
        )

        return "", 204

    async def action_resume_clock(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: SlaClockResumeValidation,
    ) -> tuple[dict, int]:
        """Resume a paused SLA clock."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "paused":
            abort(409, "Only paused clocks can be resumed.")

        now = self._now_utc()
        elapsed = int(current.elapsed_seconds or 0)
        deadline_at = await self._compute_deadline(
            tenant_id=tenant_id,
            clock=current,
            at_time=now,
            elapsed_seconds=elapsed,
        )

        await self._update_clock_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "running",
                "last_started_at": now,
                "paused_at": None,
                "stopped_at": None,
                "deadline_at": deadline_at,
                "last_actor_user_id": auth_user_id,
            },
        )

        return "", 204

    async def action_stop_clock(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: SlaClockStopValidation,
    ) -> tuple[dict, int]:
        """Stop a running/paused SLA clock."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status not in {"running", "paused"}:
            abort(409, "Only running or paused clocks can be stopped.")

        now = self._now_utc()
        elapsed = (
            self._elapsed_with_open_segment(current, now)
            if current.status == "running"
            else int(current.elapsed_seconds or 0)
        )

        await self._update_clock_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "stopped",
                "elapsed_seconds": elapsed,
                "last_started_at": None,
                "paused_at": None,
                "stopped_at": now,
                "last_actor_user_id": auth_user_id,
            },
        )

        return "", 204

    async def action_mark_breached(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: SlaClockMarkBreachedValidation,
    ) -> tuple[dict, int]:
        """Mark a clock as breached and append an immutable breach event."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        now = self._now_utc()
        elapsed = self._elapsed_with_open_segment(current, now)

        await self._update_clock_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "breached",
                "elapsed_seconds": elapsed,
                "last_started_at": None,
                "paused_at": None,
                "stopped_at": current.stopped_at or now,
                "deadline_at": current.deadline_at or now,
                "is_breached": True,
                "breached_at": current.breached_at or now,
                "breach_count": int(current.breach_count or 0) + 1,
                "last_actor_user_id": auth_user_id,
            },
        )

        await self._append_breach_event(
            tenant_id=tenant_id,
            clock_id=entity_id,
            actor_user_id=auth_user_id,
            data=data,
            occurred_at=now,
        )

        return "", 204
