"""Branch tests for RelationalWebRuntimeStore helper behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from mugen.core.gateway.storage.web_runtime.relational_store import (
    RelationalWebRuntimeStore,
)


class _ResultMappings:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _ResultMappings(self._row)


class _Session:
    def __init__(self, row):
        self._row = row
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, stmt, params=None):  # noqa: ARG002
        _ = stmt
        return _Result(self._row)


def _session_provider(session):
    @asynccontextmanager
    async def _cm():
        yield session

    return _cm


class TestRelationalWebRuntimeStore(unittest.IsolatedAsyncioTestCase):
    """Covers currently-unhit helper branches in the relational web store."""

    def _build_store(
        self,
        *,
        row,
        readiness_probe=None,
        session=None,
    ) -> tuple[RelationalWebRuntimeStore, _Session]:
        active_session = session or _Session(row)
        runtime = SimpleNamespace(engine=None, session_maker=Mock())
        store = RelationalWebRuntimeStore(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
            relational_runtime=runtime,
            session_provider=_session_provider(active_session),
            readiness_probe=readiness_probe,
        )
        return store, active_session

    def test_init_requires_relational_runtime(self) -> None:
        with self.assertRaises(TypeError):
            RelationalWebRuntimeStore(  # type: ignore[call-arg]
                config=SimpleNamespace(),
                logging_gateway=Mock(),
            )

    async def test_check_readiness_awaits_probe(self) -> None:
        readiness_called = False

        async def _ready():
            nonlocal readiness_called
            readiness_called = True

        store, _ = self._build_store(
            row={
                "web_queue_job": "mugen.web_queue_job",
                "web_conversation_state": "mugen.web_conversation_state",
                "web_conversation_event": "mugen.web_conversation_event",
                "web_media_token": "mugen.web_media_token",
            },
            readiness_probe=_ready,
        )
        await store.check_readiness()
        self.assertTrue(readiness_called)

    async def test_check_readiness_handles_non_awaitable_probe(self) -> None:
        store, _ = self._build_store(
            row={
                "web_queue_job": "mugen.web_queue_job",
                "web_conversation_state": "mugen.web_conversation_state",
                "web_conversation_event": "mugen.web_conversation_event",
                "web_media_token": "mugen.web_media_token",
            },
            readiness_probe=lambda: "ok",
        )
        await store.check_readiness()

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
        with self.assertRaisesRegex(RuntimeError, "tables unavailable"):
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

    async def test_aclose_noops_when_engine_not_initialized(self) -> None:
        store, _ = self._build_store(row={})
        await store.aclose()

    async def test_aclose_disposes_engine_when_present(self) -> None:
        store, _ = self._build_store(row={})
        await store.aclose()

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
