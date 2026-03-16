"""Unit tests for ops_metering usage-session lifecycle behavior."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.ops_metering.api.validation import (
    UsageSessionPauseValidation,
    UsageSessionResumeValidation,
    UsageSessionStartValidation,
    UsageSessionStopValidation,
)
from mugen.core.plugin.ops_metering.domain import UsageRecordDE, UsageSessionDE
from mugen.core.plugin.ops_metering.service.usage_session import UsageSessionService


class TestOpsMeteringLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests usage session lifecycle transitions on UsageSessionService."""

    async def test_start_session_sets_running_state(self) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = UsageSessionService(table="ops_metering_usage_session", rsg=Mock())
        now = datetime(2026, 2, 13, 16, 0, tzinfo=timezone.utc)
        svc._now_utc = lambda: now

        current = UsageSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            meter_definition_id=uuid.uuid4(),
            status="idle",
            row_version=2,
            elapsed_seconds=0,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)

        result = await svc.action_start_session(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=actor_id,
            data=UsageSessionStartValidation(row_version=2),
        )

        self.assertEqual(result, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "running")
        self.assertEqual(changes["last_started_at"], now)
        self.assertEqual(changes["last_actor_user_id"], actor_id)

    async def test_pause_resume_stop_updates_elapsed_and_writes_usage_record(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        meter_definition_id = uuid.uuid4()
        account_id = uuid.uuid4()

        svc = UsageSessionService(table="ops_metering_usage_session", rsg=Mock())

        pause_now = datetime(2026, 2, 13, 16, 2, tzinfo=timezone.utc)
        resume_now = datetime(2026, 2, 13, 16, 10, tzinfo=timezone.utc)
        stop_now = datetime(2026, 2, 13, 16, 15, tzinfo=timezone.utc)

        # pause (running -> paused)
        running = UsageSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            account_id=account_id,
            status="running",
            row_version=4,
            elapsed_seconds=30,
            last_started_at=datetime(2026, 2, 13, 16, 0, tzinfo=timezone.utc),
        )
        svc._now_utc = lambda: pause_now
        svc.get = AsyncMock(return_value=running)
        svc.update_with_row_version = AsyncMock(return_value=running)

        pause_result = await svc.action_pause_session(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=actor_id,
            data=UsageSessionPauseValidation(row_version=4),
        )

        self.assertEqual(pause_result, ("", 204))
        pause_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(pause_changes["status"], "paused")
        self.assertEqual(pause_changes["elapsed_seconds"], 150)

        # resume (paused -> running)
        paused = UsageSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            account_id=account_id,
            status="paused",
            row_version=5,
            elapsed_seconds=150,
        )
        svc._now_utc = lambda: resume_now
        svc.get = AsyncMock(return_value=paused)
        svc.update_with_row_version = AsyncMock(return_value=paused)

        resume_result = await svc.action_resume_session(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=actor_id,
            data=UsageSessionResumeValidation(row_version=5),
        )

        self.assertEqual(resume_result, ("", 204))
        resume_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(resume_changes["status"], "running")
        self.assertEqual(resume_changes["last_started_at"], resume_now)

        # stop (running -> stopped)
        resumed_running = UsageSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            account_id=account_id,
            status="running",
            row_version=6,
            elapsed_seconds=150,
            last_started_at=resume_now,
        )
        stopped = UsageSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            account_id=account_id,
            status="stopped",
            row_version=7,
            elapsed_seconds=450,
            usage_record_id=None,
        )

        svc._now_utc = lambda: stop_now
        svc.get = AsyncMock(return_value=resumed_running)
        svc.update_with_row_version = AsyncMock(return_value=stopped)
        svc._usage_record_service.create = AsyncMock(
            return_value=UsageRecordDE(id=uuid.uuid4())
        )
        svc.update = AsyncMock(return_value=stopped)

        stop_result = await svc.action_stop_session(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=actor_id,
            data=UsageSessionStopValidation(row_version=6),
        )

        self.assertEqual(stop_result, ("", 204))
        stop_changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(stop_changes["status"], "stopped")
        self.assertEqual(stop_changes["elapsed_seconds"], 450)

        created_payload = svc._usage_record_service.create.await_args.args[0]
        self.assertEqual(created_payload["tenant_id"], tenant_id)
        self.assertEqual(created_payload["usage_session_id"], session_id)
        self.assertEqual(created_payload["measured_minutes"], 8)

    async def test_pause_requires_running_state(self) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        svc = UsageSessionService(table="ops_metering_usage_session", rsg=Mock())
        svc.get = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                meter_definition_id=uuid.uuid4(),
                status="idle",
                row_version=1,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_pause_session(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=uuid.uuid4(),
                data=UsageSessionPauseValidation(row_version=1),
            )

        self.assertEqual(ctx.exception.code, 409)
