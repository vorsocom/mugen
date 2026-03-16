"""Unit tests for the shared messaging ingress service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.dialects.postgresql import JSONB

from mugen.core.contract.service.ingress import (
    MessagingIngressCheckpointUpdate,
    MessagingIngressEvent,
    MessagingIngressStageEntry,
)
from mugen.core.service.ingress import DefaultMessagingIngressService


_MISSING = object()
_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000101")


class _FakeResult:
    def __init__(
        self,
        *,
        scalar: object | None = None,
        mapping_one: dict | None = None,
        mappings_all: list[dict] | None = None,
    ) -> None:
        self._scalar = scalar
        self._mapping_one = mapping_one
        self._mappings_all = list(mappings_all or [])

    def scalar_one_or_none(self):
        return self._scalar

    def mappings(self):
        return self

    def one_or_none(self):
        return self._mapping_one

    def all(self):
        return self._mappings_all


class _FakeSession:
    def __init__(self, results: list[object] | None = None) -> None:
        self._results = list(results or [])
        self.execute_calls: list[tuple[object, dict | None]] = []
        self.entered = False
        self.exited = False
        self.begin_entered = False
        self.begin_exited = False

    async def execute(self, statement, params=None):
        self.execute_calls.append((statement, params))
        if self._results:
            result = self._results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return _FakeResult()

    def begin(self):
        session = self

        class _BeginContext:
            async def __aenter__(self_inner):
                session.begin_entered = True
                return session

            async def __aexit__(self_inner, exc_type, exc, tb):
                session.begin_exited = True
                return False

        return _BeginContext()


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self):
        self._session.entered = True
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        self._session.exited = True
        return False


class _FakeSessionMaker:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return _FakeSessionContext(self._session)


class _FakeConnection:
    def __init__(self, results: list[object] | None = None) -> None:
        self._results = list(results or [])
        self.execute_calls: list[tuple[object, dict | None]] = []

    async def execute(self, statement, params=None):
        self.execute_calls.append((statement, params))
        if self._results:
            result = self._results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return _FakeResult()


class _FakeConnectContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def connect(self):
        return _FakeConnectContext(self._connection)


def _make_config(*, ingress: object = _MISSING) -> SimpleNamespace:
    config = SimpleNamespace(
        rdbms=SimpleNamespace(
            migration_tracks=SimpleNamespace(
                core=SimpleNamespace(schema="core"),
            )
        )
    )
    if ingress is not _MISSING:
        config.ingress = ingress
    return config


def _make_event(**overrides) -> MessagingIngressEvent:
    payload = {
        "version": 1,
        "platform": "matrix",
        "client_profile_id": _CLIENT_PROFILE_ID,
        "source_mode": "sync_room_message",
        "event_type": "RoomMessageText",
        "event_id": "$event-1",
        "dedupe_key": "matrix:$event-1",
        "identifier_type": "recipient_user_id",
        "identifier_value": "@bot:test",
        "room_id": "!room:test",
        "sender": "@user:test",
        "payload": {"body": "hello"},
        "provider_context": {"sync_batch": "s1"},
        "received_at": datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return MessagingIngressEvent(**payload)


def _make_entry(**event_overrides) -> MessagingIngressStageEntry:
    ttl = event_overrides.pop("dedupe_ttl_seconds", 86400)
    command = event_overrides.pop("ipc_command", "matrix_ingress_event")
    return MessagingIngressStageEntry(
        ipc_command=command,
        event=_make_event(**event_overrides),
        dedupe_ttl_seconds=ttl,
    )


def _make_checkpoint(**overrides) -> MessagingIngressCheckpointUpdate:
    payload = {
        "platform": "matrix",
        "client_profile_id": _CLIENT_PROFILE_ID,
        "checkpoint_key": "sync_token",
        "checkpoint_value": "next-batch",
        "provider_context": {"source": "sync"},
        "observed_at": datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return MessagingIngressCheckpointUpdate(**payload)


def _make_row(**overrides) -> dict:
    row = {
        "id": 7,
        "version": 1,
        "platform": "matrix",
        "client_profile_id": _CLIENT_PROFILE_ID,
        "ipc_command": "matrix_ingress_event",
        "source_mode": "sync_room_message",
        "event_type": "RoomMessageText",
        "event_id": "$event-1",
        "dedupe_key": "matrix:$event-1",
        "identifier_type": "recipient_user_id",
        "identifier_value": "@bot:test",
        "room_id": "!room:test",
        "sender": "@user:test",
        "payload": {"body": "hello"},
        "provider_context": {"sync_batch": "s1"},
        "received_at": datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc),
        "attempts": 1,
    }
    row.update(overrides)
    return row


def _make_service(
    *,
    ingress: object = _MISSING,
    session: _FakeSession | None = None,
    connection: _FakeConnection | None = None,
):
    session = session or _FakeSession()
    connection = connection or _FakeConnection()
    runtime = SimpleNamespace(
        session_maker=_FakeSessionMaker(session),
        engine=_FakeEngine(connection),
    )
    ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock())
    logging_gateway = Mock()
    service = DefaultMessagingIngressService(
        config=_make_config(ingress=ingress),
        logging_gateway=logging_gateway,
        relational_runtime=runtime,
        ipc_service=ipc_service,
    )
    return service, session, connection, logging_gateway, ipc_service


def _bind_session_provider(
    service: DefaultMessagingIngressService,
    session: _FakeSession,
) -> None:
    @asynccontextmanager
    async def _session_provider():
        yield session

    service._session_provider = _session_provider


class TestMugenServiceIngress(unittest.IsolatedAsyncioTestCase):
    """Covers lifecycle, staging, and worker branches for ingress service."""

    async def test_constructor_defaults_session_provider_schema_and_utc_now(self) -> None:
        service, session, _, _, _ = _make_service()

        async with service._session_provider() as provided_session:  # pylint: disable=protected-access
            self.assertIs(provided_session, session)

        statement = service._schema_sql("SELECT * FROM mugen.messaging_ingress_event")  # pylint: disable=protected-access
        now = service._utc_now()  # pylint: disable=protected-access

        self.assertTrue(session.entered)
        self.assertTrue(session.exited)
        self.assertTrue(session.begin_entered)
        self.assertTrue(session.begin_exited)
        self.assertIsInstance(service._ingress_config(), SimpleNamespace)  # pylint: disable=protected-access
        self.assertIn("core.messaging_ingress_event", str(statement))
        self.assertEqual(service._worker_poll_seconds, 0.5)  # pylint: disable=protected-access
        self.assertEqual(service._worker_lease_seconds, 60)  # pylint: disable=protected-access
        self.assertEqual(service._worker_batch_size, 50)  # pylint: disable=protected-access
        self.assertEqual(service._max_attempts, 5)  # pylint: disable=protected-access
        self.assertEqual(now.tzinfo, timezone.utc)

    async def test_constructor_resolves_explicit_ingress_worker_settings(self) -> None:
        service, _, _, _, _ = _make_service(
            ingress=SimpleNamespace(
                worker_poll_seconds="1.25",
                worker_lease_seconds="7",
                worker_batch_size="9",
                max_attempts="11",
            )
        )

        self.assertEqual(service._worker_poll_seconds, 1.25)  # pylint: disable=protected-access
        self.assertEqual(service._worker_lease_seconds, 7)  # pylint: disable=protected-access
        self.assertEqual(service._worker_batch_size, 9)  # pylint: disable=protected-access
        self.assertEqual(service._max_attempts, 11)  # pylint: disable=protected-access

    async def test_check_readiness_success_and_failure_paths(self) -> None:
        service, _, connection, _, _ = _make_service()
        connection._results = [  # pylint: disable=protected-access
            _FakeResult(),
            _FakeResult(
                mapping_one={
                    "messaging_ingress_event": "core.messaging_ingress_event",
                    "messaging_ingress_dedup": "core.messaging_ingress_dedup",
                    "messaging_ingress_dead_letter": "core.messaging_ingress_dead_letter",
                    "messaging_ingress_checkpoint": "core.messaging_ingress_checkpoint",
                }
            ),
        ]
        await service.check_readiness()

        service, _, connection, _, _ = _make_service()
        connection._results = [_FakeResult(), _FakeResult(mapping_one=None)]  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "Messaging ingress readiness query failed"):
            await service.check_readiness()

        service, _, connection, _, _ = _make_service()
        connection._results = [  # pylint: disable=protected-access
            _FakeResult(),
            _FakeResult(
                mapping_one={
                    "messaging_ingress_event": "",
                    "messaging_ingress_dedup": None,
                    "messaging_ingress_dead_letter": "core.messaging_ingress_dead_letter",
                    "messaging_ingress_checkpoint": "",
                }
            ),
        ]
        with self.assertRaisesRegex(
            RuntimeError,
            "messaging_ingress_checkpoint, messaging_ingress_dedup, messaging_ingress_event",
        ):
            await service.check_readiness()

    async def test_ensure_started_reuses_existing_worker_and_starts_new_task(self) -> None:
        service, _, _, _, _ = _make_service()
        existing_task = asyncio.create_task(asyncio.sleep(10))
        self.addAsyncCleanup(asyncio.gather, existing_task, return_exceptions=True)
        service._worker_task = existing_task  # pylint: disable=protected-access

        await service.ensure_started()
        self.assertIs(service._worker_task, existing_task)  # pylint: disable=protected-access

        existing_task.cancel()
        await asyncio.gather(existing_task, return_exceptions=True)

        started = asyncio.Event()

        async def _fake_worker_loop():
            started.set()
            await service._worker_stop.wait()  # pylint: disable=protected-access

        service._worker_task = None  # pylint: disable=protected-access
        service._worker_loop = _fake_worker_loop  # type: ignore[method-assign]  # pylint: disable=protected-access

        await service.ensure_started()
        await asyncio.wait_for(started.wait(), timeout=1.0)
        self.assertIsNotNone(service._worker_task)  # pylint: disable=protected-access
        await service.aclose()

    async def test_stage_validates_arguments(self) -> None:
        service, session, _, _, _ = _make_service()
        _bind_session_provider(service, session)
        service.ensure_started = AsyncMock()  # type: ignore[method-assign]

        with self.assertRaisesRegex(TypeError, "stage entries must be a list"):
            await service.stage("bad")  # type: ignore[arg-type]

        with self.assertRaisesRegex(
            TypeError,
            "stage entries must contain MessagingIngressStageEntry values",
        ):
            await service.stage([object()])  # type: ignore[list-item]

        with self.assertRaisesRegex(
            TypeError,
            "stage checkpoints must be a list when provided",
        ):
            await service.stage([_make_entry()], checkpoints=object())  # type: ignore[arg-type]

        with self.assertRaisesRegex(
            TypeError,
            "stage checkpoints must contain MessagingIngressCheckpointUpdate values",
        ):
            await service.stage([_make_entry()], checkpoints=[object()])  # type: ignore[list-item]

    async def test_stage_counts_staged_duplicates_and_checkpoints(self) -> None:
        service, session, _, _, _ = _make_service()
        _bind_session_provider(service, session)
        service.ensure_started = AsyncMock()  # type: ignore[method-assign]
        service._insert_dedup_row = AsyncMock(side_effect=[True, False])  # type: ignore[method-assign]  # pylint: disable=protected-access
        service._insert_event_row = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        service._upsert_checkpoint_row = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access

        result = await service.stage(
            [_make_entry(event_id="$1", dedupe_key="d1"), _make_entry(event_id="$2", dedupe_key="d2")],
            checkpoints=[_make_checkpoint()],
        )

        self.assertEqual(result.staged_count, 1)
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(result.checkpoint_count, 1)
        service.ensure_started.assert_awaited_once()
        self.assertEqual(service._insert_dedup_row.await_count, 2)  # type: ignore[attr-defined]  # pylint: disable=protected-access
        self.assertEqual(service._insert_event_row.await_count, 1)  # type: ignore[attr-defined]  # pylint: disable=protected-access
        self.assertEqual(service._upsert_checkpoint_row.await_count, 1)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    async def test_aclose_handles_none_and_running_worker_task(self) -> None:
        service, _, _, _, _ = _make_service()

        await service.aclose()

        service._worker_task = asyncio.create_task(asyncio.sleep(10))  # pylint: disable=protected-access
        await service.aclose()

        self.assertTrue(service._worker_stop.is_set())  # pylint: disable=protected-access
        self.assertIsNone(service._worker_task)  # pylint: disable=protected-access

    async def test_get_checkpoint_returns_none_for_missing_and_blank_and_value_for_text(
        self,
    ) -> None:
        service, session, _, _, _ = _make_service()
        _bind_session_provider(service, session)

        session._results = [_FakeResult(mapping_one=None)]  # pylint: disable=protected-access
        self.assertIsNone(
            await service.get_checkpoint(
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                checkpoint_key="sync_token",
            )
        )

        session._results = [  # pylint: disable=protected-access
            _FakeResult(mapping_one={"checkpoint_value": "   "})
        ]
        self.assertIsNone(
            await service.get_checkpoint(
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                checkpoint_key="sync_token",
            )
        )

        session._results = [  # pylint: disable=protected-access
            _FakeResult(mapping_one={"checkpoint_value": "next-batch"})
        ]
        self.assertEqual(
            await service.get_checkpoint(
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                checkpoint_key="sync_token",
            ),
            "next-batch",
        )

    async def test_insert_dedup_row_handles_insert_and_duplicate_paths(self) -> None:
        service, session, _, _, _ = _make_service()
        fixed_now = datetime(2026, 3, 8, 13, 0, 0, tzinfo=timezone.utc)
        service._utc_now = Mock(return_value=fixed_now)  # type: ignore[method-assign]  # pylint: disable=protected-access

        session._results = [_FakeResult(scalar=123)]  # pylint: disable=protected-access
        inserted = await service._insert_dedup_row(session, entry=_make_entry())  # pylint: disable=protected-access
        self.assertTrue(inserted)
        self.assertEqual(session.execute_calls[0][1]["expires_at"], fixed_now + timedelta(seconds=86400))

        session.execute_calls.clear()
        session._results = [_FakeResult(scalar=None), _FakeResult()]  # pylint: disable=protected-access
        inserted = await service._insert_dedup_row(  # pylint: disable=protected-access
            session,
            entry=_make_entry(event_id=None, dedupe_key="dedupe-2", dedupe_ttl_seconds=30),
        )
        self.assertFalse(inserted)
        self.assertEqual(len(session.execute_calls), 2)
        self.assertIn("UPDATE core.messaging_ingress_dedup", str(session.execute_calls[1][0]))
        self.assertEqual(
            session.execute_calls[1][1]["expires_at"],
            fixed_now + timedelta(seconds=30),
        )

    async def test_insert_event_row_and_checkpoint_upsert_bind_expected_values(self) -> None:
        service, session, _, _, _ = _make_service()
        entry = _make_entry()
        checkpoint = _make_checkpoint()

        await service._insert_event_row(session, entry=entry)  # pylint: disable=protected-access
        await service._upsert_checkpoint_row(session, checkpoint=checkpoint)  # pylint: disable=protected-access

        self.assertEqual(len(session.execute_calls), 2)
        event_stmt, event_params = session.execute_calls[0]
        checkpoint_stmt, checkpoint_params = session.execute_calls[1]
        self.assertEqual(event_params["ipc_command"], "matrix_ingress_event")
        self.assertEqual(event_params["payload"], {"body": "hello"})
        self.assertEqual(event_params["provider_context"], {"sync_batch": "s1"})
        self.assertEqual(checkpoint_params["checkpoint_key"], "sync_token")
        self.assertEqual(checkpoint_params["provider_context"], {"source": "sync"})
        self.assertIsInstance(event_stmt._bindparams["payload"].type, JSONB)  # pylint: disable=protected-access
        self.assertIsInstance(  # pylint: disable=protected-access
            event_stmt._bindparams["provider_context"].type,
            JSONB,
        )
        self.assertIsInstance(  # pylint: disable=protected-access
            checkpoint_stmt._bindparams["provider_context"].type,
            JSONB,
        )

    def test_jsonb_sql_without_parameter_names_returns_plain_clause(self) -> None:
        service, _, _, _, _ = _make_service()

        clause = service._jsonb_sql("SELECT 1")  # pylint: disable=protected-access

        self.assertEqual(str(clause), "SELECT 1")
        self.assertEqual(clause._bindparams, {})  # pylint: disable=protected-access

    async def test_worker_loop_sleeps_when_empty_and_logs_dispatch_failure(self) -> None:
        service, _, _, logging_gateway, _ = _make_service()

        async def _claim_batch():
            if getattr(_claim_batch, "called", False):
                service._worker_stop.set()  # pylint: disable=protected-access
                return []
            _claim_batch.called = True
            return [{"id": 1}, {"id": 2}]

        _claim_batch.called = False  # type: ignore[attr-defined]
        service._claim_batch = AsyncMock(side_effect=_claim_batch)  # type: ignore[method-assign]  # pylint: disable=protected-access
        service._dispatch_claimed_row = AsyncMock(side_effect=[None, RuntimeError("boom")])  # type: ignore[method-assign]  # pylint: disable=protected-access

        async def _fake_sleep(_seconds):
            return None

        with patch("mugen.core.service.ingress.asyncio.sleep", new=AsyncMock(side_effect=_fake_sleep)) as sleep_mock:
            await service._worker_loop()  # pylint: disable=protected-access

        sleep_mock.assert_awaited_once()
        logging_gateway.error.assert_called_once()
        self.assertIn("event_id=2", logging_gateway.error.call_args.args[0])

    async def test_worker_loop_propagates_cancellation(self) -> None:
        service, _, _, _, _ = _make_service()
        service._claim_batch = AsyncMock(return_value=[{"id": 9}])  # type: ignore[method-assign]  # pylint: disable=protected-access
        service._dispatch_claimed_row = AsyncMock(side_effect=asyncio.CancelledError())  # type: ignore[method-assign]  # pylint: disable=protected-access

        with self.assertRaises(asyncio.CancelledError):
            await service._worker_loop()  # pylint: disable=protected-access

    async def test_claim_batch_returns_claimed_rows(self) -> None:
        service, session, _, _, _ = _make_service()
        _bind_session_provider(service, session)
        fixed_now = datetime(2026, 3, 8, 13, 30, 0, tzinfo=timezone.utc)
        service._utc_now = Mock(return_value=fixed_now)  # type: ignore[method-assign]  # pylint: disable=protected-access
        session._results = [  # pylint: disable=protected-access
            _FakeResult(mappings_all=[_make_row(id=1), _make_row(id=2, event_id="$event-2")])
        ]

        rows = await service._claim_batch()  # pylint: disable=protected-access

        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertEqual(
            session.execute_calls[0][1]["lease_expires_at"],
            fixed_now + timedelta(seconds=service._worker_lease_seconds),  # pylint: disable=protected-access
        )
        self.assertEqual(
            session.execute_calls[0][1]["batch_size"],
            service._worker_batch_size,  # pylint: disable=protected-access
        )

    async def test_build_event_payload_normalizes_optional_fields(self) -> None:
        service, _, _, _, _ = _make_service()
        payload = service._build_event_payload(  # pylint: disable=protected-access
            _make_row(
                version=None,
                event_id="   ",
                identifier_value="   ",
                room_id="  ",
                sender="  ",
                payload=[],
                provider_context=[],
                received_at=datetime(2026, 3, 8, 14, 0, 0),
            )
        )

        self.assertEqual(payload["version"], 1)
        self.assertIsNone(payload["event_id"])
        self.assertIsNone(payload["identifier_value"])
        self.assertIsNone(payload["room_id"])
        self.assertIsNone(payload["sender"])
        self.assertEqual(payload["payload"], {})
        self.assertEqual(payload["provider_context"], {})
        self.assertEqual(payload["received_at"], "2026-03-08T14:00:00+00:00")

    async def test_dispatch_claimed_row_handles_success_error_and_exception(self) -> None:
        service, _, _, _, ipc_service = _make_service()
        row = _make_row(id=11)
        service._mark_completed = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        service._mark_failed = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access

        ipc_service.handle_ipc_request.return_value = SimpleNamespace(errors=[])
        await service._dispatch_claimed_row(row)  # pylint: disable=protected-access
        request = ipc_service.handle_ipc_request.await_args.args[0]
        self.assertEqual(request.platform, "matrix")
        self.assertEqual(request.command, "matrix_ingress_event")
        self.assertEqual(request.data["event_id"], "$event-1")
        service._mark_completed.assert_awaited_once_with(row_id=11)
        self.assertEqual(service._mark_failed.await_count, 0)  # type: ignore[attr-defined]  # pylint: disable=protected-access

        service._mark_completed.reset_mock()  # type: ignore[attr-defined]  # pylint: disable=protected-access
        service._mark_failed.reset_mock()  # type: ignore[attr-defined]  # pylint: disable=protected-access
        ipc_service.handle_ipc_request.reset_mock()
        ipc_service.handle_ipc_request.return_value = SimpleNamespace(
            errors=[SimpleNamespace(code="", error="")]
        )
        await service._dispatch_claimed_row(row)  # pylint: disable=protected-access
        service._mark_failed.assert_awaited_once_with(  # pylint: disable=protected-access
            row=row,
            reason_code="handler_error",
            error_message="IPC handler returned an error.",
        )

        service._mark_failed.reset_mock()  # type: ignore[attr-defined]  # pylint: disable=protected-access
        ipc_service.handle_ipc_request.reset_mock()
        ipc_service.handle_ipc_request.side_effect = ValueError("boom")
        await service._dispatch_claimed_row(row)  # pylint: disable=protected-access
        service._mark_failed.assert_awaited_once_with(  # pylint: disable=protected-access
            row=row,
            reason_code="ValueError",
            error_message="boom",
        )

    async def test_mark_completed_updates_event_row(self) -> None:
        service, session, _, _, _ = _make_service()
        _bind_session_provider(service, session)

        await service._mark_completed(row_id=123)  # pylint: disable=protected-access

        self.assertEqual(len(session.execute_calls), 1)
        self.assertIn("SET status = 'completed'", str(session.execute_calls[0][0]))
        self.assertEqual(session.execute_calls[0][1], {"row_id": 123})

    async def test_mark_failed_dead_letters_at_max_attempts_and_requeues_otherwise(
        self,
    ) -> None:
        service, session, _, _, _ = _make_service()
        _bind_session_provider(service, session)
        fixed_now = datetime(2026, 3, 8, 15, 0, 0, tzinfo=timezone.utc)
        service._utc_now = Mock(return_value=fixed_now)  # type: ignore[method-assign]  # pylint: disable=protected-access

        await service._mark_failed(  # pylint: disable=protected-access
            row=_make_row(
                id=55,
                attempts=service._max_attempts,  # pylint: disable=protected-access
                payload=[],
                provider_context=[],
            ),
            reason_code="handler_error",
            error_message="bad payload",
        )

        self.assertEqual(len(session.execute_calls), 2)
        dead_letter_stmt, dead_letter_params = session.execute_calls[0]
        failed_params = session.execute_calls[1][1]
        self.assertEqual(dead_letter_params["source_event_id"], 55)
        self.assertEqual(dead_letter_params["payload"], {})
        self.assertEqual(dead_letter_params["provider_context"], {})
        self.assertEqual(dead_letter_params["first_failed_at"], fixed_now)
        self.assertEqual(dead_letter_params["last_failed_at"], fixed_now)
        self.assertIsInstance(  # pylint: disable=protected-access
            dead_letter_stmt._bindparams["payload"].type,
            JSONB,
        )
        self.assertIsInstance(  # pylint: disable=protected-access
            dead_letter_stmt._bindparams["provider_context"].type,
            JSONB,
        )
        self.assertEqual(
            failed_params,
            {
                "row_id": 55,
                "reason_code": "handler_error",
                "error_message": "bad payload",
            },
        )

        session.execute_calls.clear()
        await service._mark_failed(  # pylint: disable=protected-access
            row=_make_row(id=77, attempts=1),
            reason_code="temporary_error",
            error_message="retry later",
        )
        self.assertEqual(len(session.execute_calls), 1)
        self.assertIn("SET status = 'queued'", str(session.execute_calls[0][0]))
        self.assertEqual(
            session.execute_calls[0][1],
            {
                "row_id": 77,
                "reason_code": "temporary_error",
                "error_message": "retry later",
            },
        )
