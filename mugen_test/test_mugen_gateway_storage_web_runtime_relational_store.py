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

    async def execute(self, stmt, params=None):  # noqa: ARG002
        _ = stmt
        return _Result(self._row)


class _RelationalGateway:
    def __init__(self, *, row, readiness=None):
        self._session = _Session(row)
        self._readiness = readiness

    def raw_session(self):
        @asynccontextmanager
        async def _cm():
            yield self._session

        return _cm()

    def check_readiness(self):
        if self._readiness is None:
            return None
        return self._readiness()


class TestRelationalWebRuntimeStore(unittest.IsolatedAsyncioTestCase):
    """Covers currently-unhit helper branches in the relational web store."""

    def _build_store(self, *, relational_gateway) -> RelationalWebRuntimeStore:
        return RelationalWebRuntimeStore(
            config=SimpleNamespace(),
            relational_storage_gateway=relational_gateway,
            logging_gateway=Mock(),
        )

    async def test_raw_session_provider_missing_raises_runtime_error(self) -> None:
        store = self._build_store(relational_gateway=object())
        with self.assertRaises(RuntimeError):
            store._raw_relational_session_provider()  # pylint: disable=protected-access

    async def test_check_readiness_awaits_relational_gateway_hook(self) -> None:
        readiness_called = False

        async def _ready():
            nonlocal readiness_called
            readiness_called = True

        store = self._build_store(
            relational_gateway=_RelationalGateway(
                row={
                    "web_queue_job": "mugen.web_queue_job",
                    "web_conversation_state": "mugen.web_conversation_state",
                    "web_conversation_event": "mugen.web_conversation_event",
                    "web_media_token": "mugen.web_media_token",
                },
                readiness=_ready,
            )
        )

        await store.check_readiness()
        self.assertTrue(readiness_called)

    async def test_check_readiness_raises_when_query_returns_no_row(self) -> None:
        store = self._build_store(relational_gateway=_RelationalGateway(row=None))
        with self.assertRaisesRegex(RuntimeError, "readiness query failed"):
            await store.check_readiness()

    async def test_check_readiness_raises_when_required_tables_missing(self) -> None:
        store = self._build_store(
            relational_gateway=_RelationalGateway(
                row={
                    "web_queue_job": None,
                    "web_conversation_state": "mugen.web_conversation_state",
                    "web_conversation_event": "mugen.web_conversation_event",
                    "web_media_token": "mugen.web_media_token",
                }
            )
        )
        with self.assertRaisesRegex(RuntimeError, "tables unavailable"):
            await store.check_readiness()

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

    async def test_check_readiness_handles_non_awaitable_gateway_hook(self) -> None:
        gateway = _RelationalGateway(
            row={
                "web_queue_job": "mugen.web_queue_job",
                "web_conversation_state": "mugen.web_conversation_state",
                "web_conversation_event": "mugen.web_conversation_event",
                "web_media_token": "mugen.web_media_token",
            },
            readiness=lambda: "ok",
        )
        store = self._build_store(relational_gateway=gateway)
        await store.check_readiness()

    async def test_check_readiness_allows_gateway_without_hook(self) -> None:
        gateway = _RelationalGateway(
            row={
                "web_queue_job": "mugen.web_queue_job",
                "web_conversation_state": "mugen.web_conversation_state",
                "web_conversation_event": "mugen.web_conversation_event",
                "web_media_token": "mugen.web_media_token",
            },
            readiness=None,
        )
        store = self._build_store(relational_gateway=gateway)
        await store.check_readiness()

    async def test_check_readiness_uses_gateway_execute_once(self) -> None:
        session = _Session(
            {
                "web_queue_job": "mugen.web_queue_job",
                "web_conversation_state": "mugen.web_conversation_state",
                "web_conversation_event": "mugen.web_conversation_event",
                "web_media_token": "mugen.web_media_token",
            }
        )
        gateway = SimpleNamespace(
            raw_session=lambda: _session_cm(session),
            check_readiness=AsyncMock(return_value=None),
        )
        store = self._build_store(relational_gateway=gateway)
        await store.check_readiness()
        gateway.check_readiness.assert_awaited_once()


def _session_cm(session):
    @asynccontextmanager
    async def _cm():
        yield session

    return _cm()
