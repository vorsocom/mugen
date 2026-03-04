"""Branch tests for RelationalWebRuntimeStore helper behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from mugen.core.gateway.storage.web_runtime.relational_store import (
    RelationalWebRuntimeStore,
)


class _ResultMappings:
    def __init__(self, rows):
        self._rows = list(rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows):
        if rows is None:
            self._rows = []
        elif isinstance(rows, list):
            self._rows = list(rows)
        else:
            self._rows = [rows]

    def mappings(self):
        return _ResultMappings(self._rows)


class _Session:
    def __init__(self, row):
        self._row = row
        self.execute = AsyncMock(side_effect=self._execute)
        self.begin = Mock(return_value=_NoopTransaction())

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # noqa: ARG002
        return False

    async def _execute(self, stmt, params=None):  # noqa: ARG002
        _ = stmt
        return _Result(self._row)


class _SequenceSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.execute = AsyncMock(side_effect=self._execute)
        self.begin = Mock(return_value=_NoopTransaction())

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # noqa: ARG002
        return False

    async def _execute(self, stmt, params=None):  # noqa: ARG002
        _ = stmt
        if not self._responses:
            return _Result(None)
        return _Result(self._responses.pop(0))


class _NoopTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # noqa: ARG002
        return False


class TestRelationalWebRuntimeStore(unittest.IsolatedAsyncioTestCase):
    """Covers currently-unhit helper branches in the relational web store."""

    def _build_store(
        self,
        *,
        row,
        session=None,
        engine=None,
        config=None,
    ) -> tuple[RelationalWebRuntimeStore, _Session]:
        active_session = session or _Session(row)
        runtime = SimpleNamespace(
            engine=engine,
            session_maker=Mock(return_value=active_session),
        )
        resolved_config = config or SimpleNamespace(
            rdbms=SimpleNamespace(
                migration_tracks=SimpleNamespace(
                    core=SimpleNamespace(schema="mugen"),
                )
            )
        )
        store = RelationalWebRuntimeStore(
            config=resolved_config,
            logging_gateway=Mock(),
            relational_runtime=runtime,
        )
        return store, active_session

    def test_init_requires_relational_runtime(self) -> None:
        with self.assertRaises(TypeError):
            RelationalWebRuntimeStore(  # type: ignore[call-arg]
                config=SimpleNamespace(),
                logging_gateway=Mock(),
            )

    async def test_check_readiness_executes_engine_probe_when_engine_present(self) -> None:
        connection = AsyncMock()
        connection.__aenter__.return_value = connection
        connection.__aexit__.return_value = False
        connection.execute = AsyncMock(return_value=None)
        engine = Mock(connect=Mock(return_value=connection))
        store, _ = self._build_store(
            row={
                "web_queue_job": "mugen.web_queue_job",
                "web_conversation_state": "mugen.web_conversation_state",
                "web_conversation_event": "mugen.web_conversation_event",
                "web_media_token": "mugen.web_media_token",
            },
            engine=engine,
        )
        await store.check_readiness()
        connection.execute.assert_awaited()

    async def test_check_readiness_raises_when_query_returns_no_row(self) -> None:
        store, _ = self._build_store(row=None)
        with self.assertRaisesRegex(RuntimeError, "readiness query failed"):
            await store.check_readiness()

    async def test_check_readiness_raises_when_required_tables_missing(self) -> None:
        store, _ = self._build_store(
            row={
                "web_queue_job": None,
                "web_conversation_state": "mugen.web_conversation_state",
                "web_conversation_event": "mugen.web_conversation_event",
                "web_media_token": "mugen.web_media_token",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "Database schema is not ready"):
            await store.check_readiness()

    async def test_check_readiness_executes_table_query_once(self) -> None:
        store, session = self._build_store(
            row={
                "web_queue_job": "mugen.web_queue_job",
                "web_conversation_state": "mugen.web_conversation_state",
                "web_conversation_event": "mugen.web_conversation_event",
                "web_media_token": "mugen.web_media_token",
            }
        )
        await store.check_readiness()
        self.assertEqual(session.execute.await_count, 1)

    async def test_check_readiness_uses_configured_core_schema(self) -> None:
        custom_schema = "core_runtime"
        config = SimpleNamespace(
            rdbms=SimpleNamespace(
                migration_tracks=SimpleNamespace(
                    core=SimpleNamespace(schema=custom_schema),
                )
            )
        )
        store, session = self._build_store(
            row={
                "web_queue_job": f"{custom_schema}.web_queue_job",
                "web_conversation_state": f"{custom_schema}.web_conversation_state",
                "web_conversation_event": f"{custom_schema}.web_conversation_event",
                "web_media_token": f"{custom_schema}.web_media_token",
            },
            config=config,
        )

        await store.check_readiness()

        readiness_sql = str(session.execute.await_args_list[0].args[0])
        self.assertIn(f"to_regclass('{custom_schema}.web_queue_job')", readiness_sql)

    async def test_aclose_noops_when_engine_not_initialized(self) -> None:
        store, _ = self._build_store(row={})
        await store.aclose()

    async def test_aclose_disposes_engine_when_present(self) -> None:
        engine = SimpleNamespace(dispose=AsyncMock())
        store, _ = self._build_store(row={}, engine=engine)
        await store.aclose()
        engine.dispose.assert_not_awaited()

    def test_datetime_and_iso_helpers_cover_naive_and_blank_paths(self) -> None:
        naive = datetime(2025, 1, 1, 0, 0, 0)
        self.assertIsNotNone(RelationalWebRuntimeStore._datetime_to_epoch(naive))
        self.assertIsNotNone(RelationalWebRuntimeStore._datetime_to_iso(naive))
        self.assertIsNone(RelationalWebRuntimeStore._iso_to_utc_datetime(""))
        self.assertIsNotNone(
            RelationalWebRuntimeStore._iso_to_utc_datetime("2025-01-01T00:00:00Z")
        )
        parsed_naive = RelationalWebRuntimeStore._iso_to_utc_datetime("2025-01-01T00:00:00")
        self.assertIsNotNone(parsed_naive)
        self.assertEqual(parsed_naive.tzinfo, timezone.utc)

    def test_parse_event_id_rejects_none_and_negative_values(self) -> None:
        self.assertIsNone(RelationalWebRuntimeStore._parse_event_id(None))
        self.assertIsNone(RelationalWebRuntimeStore._parse_event_id(-1))

    def test_queue_job_record_to_payload_handles_attr_rows_without_dict_payload(self) -> None:
        class _AttrRow:  # pylint: disable=too-few-public-methods
            job_id = "job-1"
            conversation_id = "conv-1"
            sender = "user-1"
            message_type = "text"
            payload = None
            client_message_id = "cid-1"
            status = "pending"
            attempts = 1
            created_at = None
            updated_at = None
            lease_expires_at = None
            error_message = None
            completed_at = None

        payload = RelationalWebRuntimeStore._queue_job_record_to_payload(_AttrRow())
        self.assertEqual(payload["id"], "job-1")
        self.assertIsNone(payload["text"])

    async def test_tail_events_since_handles_generation_reset_and_row_normalization(
        self,
    ) -> None:
        session = _SequenceSession(
            responses=[
                {"stream_generation": "gen-b"},
                [
                    {
                        "event_id": "1",
                        "event_type": "system",
                        "payload": {"ok": True},
                        "created_at": None,
                        "stream_generation": "gen-b",
                        "stream_version": "2",
                    },
                    {
                        "event_id": "bad",
                        "event_type": "skip",
                        "payload": {"skip": True},
                        "created_at": None,
                        "stream_generation": "gen-b",
                        "stream_version": "3",
                    },
                    {
                        "event_id": "3",
                        "event_type": None,
                        "payload": "not-a-dict",
                        "created_at": None,
                        "stream_generation": None,
                        "stream_version": "bad",
                    },
                ],
            ],
        )
        store, _ = self._build_store(row=None, session=session)

        batch = await store.tail_events_since(
            conversation_id="conv-1",
            stream_generation="gen-a",
            after_event_id=99,
            limit=1000,
        )

        self.assertEqual(batch.stream_generation, "gen-b")
        self.assertEqual(batch.max_event_id, 3)
        self.assertEqual(batch.requested_after_event_id, 99)
        self.assertEqual(batch.effective_after_event_id, 0)
        self.assertEqual(batch.first_event_id, 1)
        self.assertEqual(len(batch.events), 2)
        self.assertEqual(batch.events[0].id, 1)
        self.assertEqual(batch.events[0].stream_version, 2)
        self.assertEqual(batch.events[1].id, 3)
        self.assertEqual(batch.events[1].event, "")
        self.assertEqual(batch.events[1].data, {})
        self.assertEqual(batch.events[1].stream_generation, "gen-b")
        self.assertEqual(batch.events[1].stream_version, 1)

    async def test_tail_events_since_uses_fallbacks_when_state_missing(self) -> None:
        session = _SequenceSession(responses=[None, []])
        store, _ = self._build_store(row=None, session=session)

        batch = await store.tail_events_since(
            conversation_id="conv-2",
            stream_generation=None,
            after_event_id=-5,
            limit=0,
        )

        self.assertIsInstance(batch.stream_generation, str)
        self.assertNotEqual(batch.stream_generation, "")
        self.assertEqual(batch.max_event_id, 0)
        self.assertEqual(batch.requested_after_event_id, 0)
        self.assertEqual(batch.effective_after_event_id, 0)
        self.assertIsNone(batch.first_event_id)
        self.assertEqual(batch.events, [])
