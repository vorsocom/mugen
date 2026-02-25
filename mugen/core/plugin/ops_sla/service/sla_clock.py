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
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    RowVersionConflict,
)
from mugen.core.plugin.ops_sla.api.validation import (
    SlaClockMarkBreachedValidation,
    SlaClockPauseValidation,
    SlaClockResumeValidation,
    SlaClockStartValidation,
    SlaClockStopValidation,
    SlaClockTickValidation,
)
from mugen.core.plugin.ops_sla.contract.service.sla_clock import ISlaClockService
from mugen.core.plugin.ops_sla.domain import (
    SlaBreachEventDE,
    SlaCalendarDE,
    SlaClockDE,
    SlaClockDefinitionDE,
    SlaClockEventDE,
    SlaPolicyDE,
    SlaTargetDE,
)
from mugen.core.plugin.ops_sla.service.sla_breach_event import SlaBreachEventService
from mugen.core.plugin.ops_sla.service.sla_calendar import SlaCalendarService
from mugen.core.plugin.ops_sla.service.sla_clock_definition import (
    SlaClockDefinitionService,
)
from mugen.core.plugin.ops_sla.service.sla_clock_event import SlaClockEventService
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
    _CLOCK_DEFINITION_TABLE = "ops_sla_clock_definition"
    _CLOCK_EVENT_TABLE = "ops_sla_clock_event"

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
        self._clock_definition_service = SlaClockDefinitionService(
            table=self._CLOCK_DEFINITION_TABLE,
            rsg=rsg,
        )
        self._clock_event_service = SlaClockEventService(
            table=self._CLOCK_EVENT_TABLE,
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

    async def _best_effort_update_clock(
        self,
        *,
        where: dict,
        expected_row_version: int,
        changes: dict,
    ) -> SlaClockDE | None:
        try:
            return await self.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            return None
        except SQLAlchemyError:
            abort(500)

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

    @staticmethod
    def _warn_offsets(value: list | None) -> set[int]:
        out: set[int] = set()
        for raw in value or []:
            try:
                parsed = int(raw)
            except (TypeError, ValueError):
                continue
            if parsed <= 0:
                continue
            out.add(parsed)
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

    @classmethod
    def _business_elapsed_seconds(
        cls,
        *,
        start_at: datetime,
        end_at: datetime,
        calendar: SlaCalendarDE,
    ) -> int:
        start_utc = cls._to_aware_utc(start_at)
        end_utc = cls._to_aware_utc(end_at)
        wall_clock_delta = int((end_utc - start_utc).total_seconds())
        if wall_clock_delta <= 0:
            return 0

        timezone_name = (calendar.timezone or "UTC").strip() or "UTC"
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            return wall_clock_delta

        business_start = calendar.business_start_time or time(hour=9)
        business_end = calendar.business_end_time or time(hour=17)
        if business_end <= business_start:
            return wall_clock_delta

        business_days = cls._business_days(calendar.business_days)
        holidays = cls._holiday_dates(calendar.holiday_refs)

        local_start = start_utc.astimezone(tz)
        local_end = end_utc.astimezone(tz)
        cursor_date = local_start.date()
        end_date = local_end.date()
        elapsed = 0

        while cursor_date <= end_date:
            if cursor_date in holidays or cursor_date.isoweekday() not in business_days:
                cursor_date += timedelta(days=1)
                continue

            day_start = datetime.combine(cursor_date, business_start, tzinfo=tz)
            day_end = datetime.combine(cursor_date, business_end, tzinfo=tz)
            segment_start = max(day_start, local_start)
            segment_end = min(day_end, local_end)
            if segment_end > segment_start:
                elapsed += int((segment_end - segment_start).total_seconds())

            cursor_date += timedelta(days=1)

        return max(0, elapsed)

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

    async def _resolve_clock_definition(
        self,
        *,
        tenant_id: uuid.UUID,
        clock_definition_id: uuid.UUID | None,
    ) -> SlaClockDefinitionDE | None:
        if clock_definition_id is None:
            return None

        return await self._clock_definition_service.get(
            {
                "tenant_id": tenant_id,
                "id": clock_definition_id,
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

    async def _resolve_target_context(
        self,
        *,
        tenant_id: uuid.UUID,
        clock: SlaClockDE,
    ) -> tuple[int, set[int], SlaClockDefinitionDE | None]:
        definition = await self._resolve_clock_definition(
            tenant_id=tenant_id,
            clock_definition_id=clock.clock_definition_id,
        )
        if definition is not None and int(definition.target_minutes or 0) > 0:
            return (
                int(definition.target_minutes),
                self._warn_offsets(definition.warn_offsets_json),
                definition,
            )

        target = await self._resolve_target(tenant_id=tenant_id, clock=clock)
        if target is None:
            return 0, set(), definition

        target_minutes = int(target.target_minutes or 0)
        warn_offsets = set()
        warn_before_minutes = int(target.warn_before_minutes or 0)
        if warn_before_minutes > 0:
            warn_offsets.add(warn_before_minutes * 60)

        return target_minutes, warn_offsets, definition

    @classmethod
    def _elapsed_with_open_segment(
        cls,
        clock: SlaClockDE,
        now: datetime,
        *,
        calendar: SlaCalendarDE | None = None,
    ) -> int:
        elapsed = int(clock.elapsed_seconds or 0)

        if clock.status != "running" or clock.last_started_at is None:
            return elapsed

        started_at = cls._to_aware_utc(clock.last_started_at)
        now_utc = cls._to_aware_utc(now)
        if calendar is None:
            delta = int((now_utc - started_at).total_seconds())
        else:
            delta = cls._business_elapsed_seconds(
                start_at=started_at,
                end_at=now_utc,
                calendar=calendar,
            )

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
        calendar: SlaCalendarDE | None = None,
    ) -> datetime | None:
        target_minutes, _warn_offsets, _definition = await self._resolve_target_context(
            tenant_id=tenant_id,
            clock=clock,
        )
        if target_minutes <= 0:
            return None

        remaining_seconds = (target_minutes * 60) - int(elapsed_seconds)
        if remaining_seconds <= 0:
            return at_time

        if calendar is None:
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

    async def _append_clock_event(
        self,
        *,
        tenant_id: uuid.UUID,
        clock: SlaClockDE,
        clock_definition: SlaClockDefinitionDE | None,
        event_type: str,
        actor_user_id: uuid.UUID,
        warned_offset_seconds: int | None,
        payload_json: dict | None,
        occurred_at: datetime,
    ) -> SlaClockEventDE:
        return await self._clock_event_service.create(
            {
                "tenant_id": tenant_id,
                "clock_id": clock.id,
                "clock_definition_id": (
                    clock_definition.id
                    if clock_definition is not None
                    else clock.clock_definition_id
                ),
                "event_type": event_type,
                "warned_offset_seconds": warned_offset_seconds,
                "trace_id": self._normalize_optional_text(clock.trace_id),
                "occurred_at": occurred_at,
                "actor_user_id": actor_user_id,
                "payload_json": payload_json,
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
                "warned_offsets_json": [],
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
        calendar = await self._resolve_calendar(tenant_id=tenant_id, clock=current)
        elapsed = self._elapsed_with_open_segment(current, now, calendar=calendar)
        deadline_at = await self._compute_deadline(
            tenant_id=tenant_id,
            clock=current,
            at_time=now,
            elapsed_seconds=elapsed,
            calendar=calendar,
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
        calendar = None
        if current.status == "running":
            calendar = await self._resolve_calendar(tenant_id=tenant_id, clock=current)
        elapsed = self._elapsed_with_open_segment(current, now, calendar=calendar)

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
        """Mark a clock as breached and append immutable breach+clock events."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        now = self._now_utc()
        calendar = (
            await self._resolve_calendar(tenant_id=tenant_id, clock=current)
            if current.status == "running"
            else None
        )
        elapsed = self._elapsed_with_open_segment(current, now, calendar=calendar)

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

        definition = await self._resolve_clock_definition(
            tenant_id=tenant_id,
            clock_definition_id=current.clock_definition_id,
        )
        if current.id is not None:
            await self._append_clock_event(
                tenant_id=tenant_id,
                clock=current,
                clock_definition=definition,
                event_type="breached",
                actor_user_id=auth_user_id,
                warned_offset_seconds=None,
                payload_json={
                    "event_type": data.event_type,
                    "reason": self._normalize_optional_text(data.reason),
                },
                occurred_at=now,
            )

        return "", 204

    async def action_tick(
        self,
        *,
        tenant_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: SlaClockTickValidation,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[dict, int]:
        """Evaluate running clocks and emit warning/breach events exactly once."""
        _ = entity_id

        now = data.now_utc or self._now_utc()
        now = self._to_aware_utc(now)
        batch_size = int(data.batch_size or 200)

        tick_where = dict(where)
        tick_where["tenant_id"] = tenant_id
        tick_where["status"] = "running"

        clocks = list(
            await self.list(
                filter_groups=[FilterGroup(where=tick_where)],
                order_by=[
                    OrderBy(field="deadline_at", descending=False),
                    OrderBy(field="created_at", descending=False),
                ],
                limit=batch_size,
            )
        )

        warned_rows: list[dict] = []
        breached_rows: list[dict] = []
        counters = {
            "Scanned": len(clocks),
            "WarnedCount": 0,
            "BreachedCount": 0,
            "ConflictCount": 0,
        }

        for clock in clocks:
            if clock.id is None:
                continue

            calendar = await self._resolve_calendar(tenant_id=tenant_id, clock=clock)
            elapsed = self._elapsed_with_open_segment(clock, now, calendar=calendar)
            deadline_at = await self._compute_deadline(
                tenant_id=tenant_id,
                clock=clock,
                at_time=now,
                elapsed_seconds=elapsed,
                calendar=calendar,
            )
            target_minutes, warn_offsets, definition = (
                await self._resolve_target_context(
                    tenant_id=tenant_id,
                    clock=clock,
                )
            )

            if target_minutes <= 0 or deadline_at is None:
                continue

            remaining_seconds = int((deadline_at - now).total_seconds())
            existing_warned = self._warn_offsets(clock.warned_offsets_json)
            new_warned = sorted(
                offset
                for offset in warn_offsets
                if offset not in existing_warned
                and remaining_seconds <= offset
                and remaining_seconds > 0
            )

            next_warned = sorted(existing_warned.union(new_warned))
            is_new_breach = remaining_seconds <= 0 and not bool(clock.is_breached)

            if not bool(data.dry_run):
                updated = await self._best_effort_update_clock(
                    where={"tenant_id": tenant_id, "id": clock.id},
                    expected_row_version=int(clock.row_version or 1),
                    changes={
                        "elapsed_seconds": elapsed,
                        "deadline_at": deadline_at,
                        "warned_offsets_json": next_warned,
                        "status": "breached" if is_new_breach else clock.status,
                        "is_breached": bool(clock.is_breached) or is_new_breach,
                        "breached_at": (
                            (clock.breached_at or now)
                            if is_new_breach
                            else clock.breached_at
                        ),
                        "breach_count": int(clock.breach_count or 0)
                        + (1 if is_new_breach else 0),
                        "last_started_at": (
                            None if is_new_breach else clock.last_started_at
                        ),
                        "paused_at": None if is_new_breach else clock.paused_at,
                        "stopped_at": (
                            (clock.stopped_at or now)
                            if is_new_breach
                            else clock.stopped_at
                        ),
                        "last_actor_user_id": auth_user_id,
                    },
                )
                if updated is None:
                    counters["ConflictCount"] += 1
                    continue

                clock = updated

                for offset in new_warned:
                    event = await self._append_clock_event(
                        tenant_id=tenant_id,
                        clock=clock,
                        clock_definition=definition,
                        event_type="warned",
                        actor_user_id=auth_user_id,
                        warned_offset_seconds=offset,
                        payload_json={
                            "remaining_seconds": remaining_seconds,
                            "target_minutes": target_minutes,
                            "deadline_at": deadline_at.isoformat(),
                        },
                        occurred_at=now,
                    )
                    warned_rows.append(
                        {
                            "ClockId": str(clock.id),
                            "ClockEventId": str(event.id),
                            "WarnedOffsetSeconds": offset,
                            "TraceId": clock.trace_id,
                        }
                    )
                    counters["WarnedCount"] += 1

                if is_new_breach:
                    event = await self._append_clock_event(
                        tenant_id=tenant_id,
                        clock=clock,
                        clock_definition=definition,
                        event_type="breached",
                        actor_user_id=auth_user_id,
                        warned_offset_seconds=None,
                        payload_json={
                            "remaining_seconds": remaining_seconds,
                            "target_minutes": target_minutes,
                            "deadline_at": deadline_at.isoformat(),
                        },
                        occurred_at=now,
                    )
                    breached_rows.append(
                        {
                            "ClockId": str(clock.id),
                            "ClockEventId": str(event.id),
                            "TraceId": clock.trace_id,
                        }
                    )
                    counters["BreachedCount"] += 1
            else:
                for offset in new_warned:
                    warned_rows.append(
                        {
                            "ClockId": str(clock.id),
                            "ClockEventId": None,
                            "WarnedOffsetSeconds": offset,
                            "TraceId": clock.trace_id,
                        }
                    )
                    counters["WarnedCount"] += 1

                if is_new_breach:
                    breached_rows.append(
                        {
                            "ClockId": str(clock.id),
                            "ClockEventId": None,
                            "TraceId": clock.trace_id,
                        }
                    )
                    counters["BreachedCount"] += 1

        return (
            {
                "Warned": warned_rows,
                "Breached": breached_rows,
                "Counters": counters,
                "DryRun": bool(data.dry_run),
                "NowUtc": now.isoformat(),
            },
            200,
        )
