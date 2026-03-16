"""Provides a CRUD service for usage session lifecycle and duration tracking."""

__all__ = ["UsageSessionService"]

from datetime import datetime, timezone
import math
import uuid

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_metering.api.validation import (
    UsageSessionPauseValidation,
    UsageSessionResumeValidation,
    UsageSessionStartValidation,
    UsageSessionStopValidation,
)
from mugen.core.plugin.ops_metering.contract.service.usage_session import (
    IUsageSessionService,
)
from mugen.core.plugin.ops_metering.domain import UsageSessionDE
from mugen.core.plugin.ops_metering.service.usage_record import UsageRecordService


class UsageSessionService(
    IRelationalService[UsageSessionDE],
    IUsageSessionService,
):
    """A CRUD service for usage session lifecycle and elapsed tracking."""

    _USAGE_RECORD_TABLE = "ops_metering_usage_record"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=UsageSessionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._usage_record_service = UsageRecordService(
            table=self._USAGE_RECORD_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    async def _get_for_action(
        self,
        *,
        where: dict,
        expected_row_version: int,
    ) -> UsageSessionDE:
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
            abort(404, "Usage session not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_session_with_row_version(
        self,
        *,
        where: dict,
        expected_row_version: int,
        changes: dict,
    ) -> UsageSessionDE:
        svc: ICrudServiceWithRowVersion[UsageSessionDE] = self

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
    def _elapsed_with_open_segment(session: UsageSessionDE, now: datetime) -> int:
        elapsed = int(session.elapsed_seconds or 0)

        if session.status != "running" or session.last_started_at is None:
            return elapsed

        started_at = session.last_started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        delta = int((now - started_at).total_seconds())
        if delta > 0:
            elapsed += delta

        return elapsed

    @staticmethod
    def _minutes_from_seconds(seconds: int) -> int:
        if seconds <= 0:
            return 0
        return int(math.ceil(seconds / 60))

    async def action_start_session(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: UsageSessionStartValidation,
    ) -> tuple[dict, int]:
        """Start an idle, paused, or stopped usage session."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "running":
            abort(409, "Session is already running.")

        now = self._now_utc()

        await self._update_session_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "running",
                "started_at": current.started_at or now,
                "last_started_at": now,
                "paused_at": None,
                "stopped_at": None,
                "last_actor_user_id": auth_user_id,
            },
        )

        return "", 204

    async def action_pause_session(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: UsageSessionPauseValidation,
    ) -> tuple[dict, int]:
        """Pause a running usage session and persist elapsed seconds."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "running":
            abort(409, "Only running sessions can be paused.")

        now = self._now_utc()
        elapsed = self._elapsed_with_open_segment(current, now)

        await self._update_session_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "paused",
                "elapsed_seconds": elapsed,
                "last_started_at": None,
                "paused_at": now,
                "stopped_at": None,
                "last_actor_user_id": auth_user_id,
            },
        )

        return "", 204

    async def action_resume_session(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: UsageSessionResumeValidation,
    ) -> tuple[dict, int]:
        """Resume a paused usage session."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status != "paused":
            abort(409, "Only paused sessions can be resumed.")

        now = self._now_utc()

        await self._update_session_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "running",
                "last_started_at": now,
                "paused_at": None,
                "stopped_at": None,
                "last_actor_user_id": auth_user_id,
            },
        )

        return "", 204

    async def action_stop_session(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: UsageSessionStopValidation,
    ) -> tuple[dict, int]:
        """Stop a running or paused session and write a usage record."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status not in {"running", "paused"}:
            abort(409, "Only running or paused sessions can be stopped.")

        now = self._now_utc()
        elapsed = (
            self._elapsed_with_open_segment(current, now)
            if current.status == "running"
            else int(current.elapsed_seconds or 0)
        )

        updated = await self._update_session_with_row_version(
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

        if updated.usage_record_id is None and elapsed > 0:
            measured_minutes = self._minutes_from_seconds(elapsed)
            try:
                created_record = await self._usage_record_service.create(
                    {
                        "tenant_id": tenant_id,
                        "meter_definition_id": updated.meter_definition_id,
                        "meter_policy_id": updated.meter_policy_id,
                        "usage_session_id": entity_id,
                        "account_id": updated.account_id,
                        "subscription_id": updated.subscription_id,
                        "price_id": updated.price_id,
                        "occurred_at": now,
                        "measured_minutes": measured_minutes,
                        "measured_units": 0,
                        "measured_tasks": 0,
                        "external_ref": f"ops_metering:session-stop:{entity_id}",
                    }
                )
            except SQLAlchemyError:
                abort(500)

            try:
                await self.update(
                    where={"tenant_id": tenant_id, "id": entity_id},
                    changes={"usage_record_id": created_record.id},
                )
            except SQLAlchemyError:
                abort(500)

        return "", 204
