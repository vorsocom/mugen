"""Unit tests for ops_metering UsageSessionService edge branches."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_metering.api.validation import (
    UsageSessionResumeValidation,
    UsageSessionStartValidation,
    UsageSessionStopValidation,
)
from mugen.core.plugin.ops_metering.domain import UsageRecordDE, UsageSessionDE
from mugen.core.plugin.ops_metering.service.usage_session import UsageSessionService


class TestUsageSessionServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Covers helper, guard, and SQL-error branches on UsageSessionService."""

    def _svc(self) -> UsageSessionService:
        return UsageSessionService(table="ops_metering_usage_session", rsg=Mock())

    def test_now_utc_returns_timezone_aware_datetime(self) -> None:
        now = UsageSessionService._now_utc()
        self.assertIsNotNone(now.tzinfo)

    def test_elapsed_with_open_segment_handles_naive_and_future_start(self) -> None:
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)

        paused = UsageSessionDE(status="paused", elapsed_seconds=9)
        self.assertEqual(UsageSessionService._elapsed_with_open_segment(paused, now), 9)

        naive_running = UsageSessionDE(
            status="running",
            elapsed_seconds=1,
            last_started_at=datetime(2026, 2, 14, 11, 59, 50),
        )
        self.assertEqual(
            UsageSessionService._elapsed_with_open_segment(naive_running, now),
            11,
        )

        future_running = UsageSessionDE(
            status="running",
            elapsed_seconds=7,
            last_started_at=datetime(2026, 2, 14, 12, 0, 5),
        )
        self.assertEqual(
            UsageSessionService._elapsed_with_open_segment(future_running, now),
            7,
        )

    def test_minutes_from_seconds_handles_non_positive_values(self) -> None:
        self.assertEqual(UsageSessionService._minutes_from_seconds(0), 0)
        self.assertEqual(UsageSessionService._minutes_from_seconds(-5), 0)
        self.assertEqual(UsageSessionService._minutes_from_seconds(61), 2)

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
            side_effect=[
                None,
                UsageSessionDE(id=where["id"], tenant_id=where["tenant_id"]),
            ]
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

    async def test_update_session_with_row_version_raises_for_conflict_sql_and_none(
        self,
    ) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("ops_metering_usage_session")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_session_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "running"},
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_session_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "running"},
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._update_session_with_row_version(
                where=where,
                expected_row_version=1,
                changes={"status": "running"},
            )
        self.assertEqual(ctx.exception.code, 404)

    async def test_action_start_session_rejects_already_running_status(self) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        svc = self._svc()
        svc.get = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                status="running",
                row_version=1,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_start_session(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=uuid.uuid4(),
                data=UsageSessionStartValidation(row_version=1),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_action_resume_session_rejects_non_paused_status(self) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        svc = self._svc()
        svc.get = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                status="idle",
                row_version=2,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_resume_session(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=uuid.uuid4(),
                data=UsageSessionResumeValidation(row_version=2),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_action_stop_session_rejects_invalid_status(self) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        svc = self._svc()
        svc.get = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                status="idle",
                row_version=3,
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_stop_session(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=uuid.uuid4(),
                data=UsageSessionStopValidation(row_version=3),
            )

        self.assertEqual(ctx.exception.code, 409)

    async def test_action_stop_session_skips_record_creation_when_already_linked(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)

        svc = self._svc()
        svc._now_utc = lambda: now
        svc.get = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                status="paused",
                elapsed_seconds=30,
                row_version=4,
            )
        )
        svc.update_with_row_version = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                meter_definition_id=uuid.uuid4(),
                status="stopped",
                elapsed_seconds=30,
                usage_record_id=uuid.uuid4(),
            )
        )
        svc._usage_record_service.create = AsyncMock(return_value=UsageRecordDE())
        svc.update = AsyncMock(return_value=Mock())

        result = await svc.action_stop_session(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=uuid.uuid4(),
            data=UsageSessionStopValidation(row_version=4),
        )

        self.assertEqual(result, ("", 204))
        svc._usage_record_service.create.assert_not_called()
        svc.update.assert_not_called()

    async def test_action_stop_session_raises_500_when_record_create_fails(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)

        svc = self._svc()
        svc._now_utc = lambda: now
        svc.get = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                meter_definition_id=uuid.uuid4(),
                status="running",
                elapsed_seconds=0,
                last_started_at=datetime(2026, 2, 14, 11, 58, tzinfo=timezone.utc),
                row_version=5,
            )
        )
        svc.update_with_row_version = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                meter_definition_id=uuid.uuid4(),
                status="stopped",
                elapsed_seconds=120,
                usage_record_id=None,
            )
        )
        svc._usage_record_service.create = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_stop_session(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=uuid.uuid4(),
                data=UsageSessionStopValidation(row_version=5),
            )

        self.assertEqual(ctx.exception.code, 500)

    async def test_action_stop_session_raises_500_when_link_update_fails(self) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)

        svc = self._svc()
        svc._now_utc = lambda: now
        svc.get = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                meter_definition_id=uuid.uuid4(),
                status="paused",
                elapsed_seconds=61,
                row_version=6,
            )
        )
        svc.update_with_row_version = AsyncMock(
            return_value=UsageSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                meter_definition_id=uuid.uuid4(),
                status="stopped",
                elapsed_seconds=61,
                usage_record_id=None,
            )
        )
        svc._usage_record_service.create = AsyncMock(
            return_value=UsageRecordDE(id=uuid.uuid4())
        )
        svc.update = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_stop_session(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=uuid.uuid4(),
                data=UsageSessionStopValidation(row_version=6),
            )

        self.assertEqual(ctx.exception.code, 500)
