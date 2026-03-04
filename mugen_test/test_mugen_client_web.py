"""Unit tests for mugen.core.client.web.DefaultWebClient."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import mugen.core.client.web as web_mod
from mugen.core.client.web import DefaultWebClient
from mugen.core.contract.gateway.storage.web_runtime import (
    WebRuntimeTailBatch,
    WebRuntimeTailEvent,
)
from mugen.core.gateway.storage.web_runtime.relational_store import (
    RelationalWebRuntimeStore,
)
from mugen.core.gateway.storage.media.provider import DefaultMediaStorageGateway
from mugen.core.contract.gateway.storage.keyval_model import KeyValEntry, KeyValListPage


class _InMemoryKeyVal:
    def __init__(self) -> None:
        self._store: dict[str, str | bytes] = {}

    def close(self) -> None:
        pass

    async def check_readiness(self) -> None:
        return None

    def get(self, key: str, decode: bool = True) -> str | bytes | None:  # noqa: ARG002
        return self._store.get(key)

    def has_key(self, key: str) -> bool:
        return key in self._store

    def keys(self) -> list[str]:
        return list(self._store.keys())

    def put(self, key: str, value: str) -> None:
        self._store[key] = value

    def remove(self, key: str) -> str | bytes | None:
        return self._store.pop(key, None)

    async def get_entry(
        self,
        key: str,
        *,
        namespace: str | None = None,
        include_expired: bool = False,  # noqa: ARG002
    ) -> KeyValEntry | None:
        raw = self.get(key, decode=False)
        if raw is None:
            return None

        if isinstance(raw, bytes):
            payload = raw
            codec = "bytes"
        else:
            payload = str(raw).encode("utf-8")
            codec = "text/utf-8"

        return KeyValEntry(
            namespace=namespace or "default",
            key=key,
            payload=payload,
            codec=codec,
            row_version=1,
        )

    async def put_json(
        self,
        key: str,
        value: dict | list,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,  # noqa: ARG002
        ttl_seconds: float | None = None,  # noqa: ARG002
    ) -> KeyValEntry:
        self.put(
            key,
            json.dumps(value, ensure_ascii=True, separators=(",", ":")),
        )
        entry = await self.get_entry(key, namespace=namespace)
        assert entry is not None
        return entry

    async def put_bytes(
        self,
        key: str,
        value: bytes,
        *,
        namespace: str | None = None,
        codec: str = "bytes",  # noqa: ARG002
        expected_row_version: int | None = None,  # noqa: ARG002
        ttl_seconds: float | None = None,  # noqa: ARG002
    ) -> KeyValEntry:
        self.put(key, value)
        entry = await self.get_entry(key, namespace=namespace)
        assert entry is not None
        return entry

    async def get_json(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> dict | list | None:
        entry = await self.get_entry(key, namespace=namespace)
        if entry is None:
            return None
        try:
            return json.loads(entry.as_text())
        except (TypeError, json.JSONDecodeError):
            return None

    async def exists(
        self,
        key: str,
        *,
        namespace: str | None = None,  # noqa: ARG002
    ) -> bool:
        return self.has_key(key)

    async def delete(
        self,
        key: str,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,  # noqa: ARG002
    ) -> KeyValEntry | None:
        removed = self.remove(key)
        if removed is None:
            return None
        if isinstance(removed, bytes):
            payload = removed
            codec = "bytes"
        else:
            payload = str(removed).encode("utf-8")
            codec = "text/utf-8"
        return KeyValEntry(
            namespace=namespace or "default",
            key=key,
            payload=payload,
            codec=codec,
            row_version=1,
        )

    async def list_keys(
        self,
        *,
        prefix: str = "",
        namespace: str | None = None,  # noqa: ARG002
        limit: int | None = None,
        cursor: str | None = None,
    ) -> KeyValListPage:
        keys = sorted([key for key in self.keys() if key.startswith(prefix)])
        start_index = 0
        if cursor not in [None, ""]:
            for index, item in enumerate(keys):
                if item > str(cursor):
                    start_index = index
                    break
            else:
                return KeyValListPage(keys=[], next_cursor=None)

        page_limit = int(limit or len(keys) or 1)
        if page_limit <= 0:
            page_limit = 1

        page_keys = keys[start_index : start_index + page_limit]
        next_cursor = None
        if (start_index + page_limit) < len(keys):
            next_cursor = page_keys[-1]
        return KeyValListPage(keys=page_keys, next_cursor=next_cursor)


class _MemoryMappings:
    def __init__(self, rows):
        self._rows = [dict(row) for row in rows]

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        if not self._rows:
            raise AssertionError("expected one row")
        return self._rows[0]

    def all(self):
        return [dict(row) for row in self._rows]


class _MemoryResult:
    def __init__(self, *, rows=None, scalar_value=None, rowcount=None):
        self._rows = [dict(row) for row in (rows or [])]
        self._scalar_value = scalar_value
        self.rowcount = rowcount

    def mappings(self):
        return _MemoryMappings(self._rows)

    def scalar(self):
        return self._scalar_value

    def first(self):
        if self._rows:
            return self._rows[0]
        return None


class _InMemoryWebRelationalState:
    def __init__(self) -> None:
        self.queue_jobs: dict[str, dict] = {}
        self.conversation_states: dict[str, dict] = {}
        self.conversation_events: dict[str, dict[int, dict]] = {}
        self.media_tokens: dict[str, dict] = {}


class _InMemoryWebRelationalSession:
    def __init__(self, state: _InMemoryWebRelationalState) -> None:
        self._state = state

    @asynccontextmanager
    async def begin(self):
        yield self

    @staticmethod
    def _norm_sql(stmt: object) -> str:
        return " ".join(str(stmt).replace("\n", " ").split()).lower()

    @staticmethod
    def _now():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)

    @staticmethod
    def _payload(value):
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _queue_row(self, job_id: str) -> dict | None:
        row = self._state.queue_jobs.get(job_id)
        if row is None:
            return None
        return dict(row)

    async def execute(self, stmt, params=None):  # noqa: C901, PLR0912, PLR0915
        sql = self._norm_sql(stmt)
        args = dict(params or {})
        now = self._now()

        if sql.startswith("select count(*) from mugen.web_queue_job where status = 'pending'"):
            pending_count = sum(
                1
                for row in self._state.queue_jobs.values()
                if str(row.get("status", "")).strip().lower() == "pending"
            )
            return _MemoryResult(scalar_value=pending_count)

        if sql.startswith("insert into mugen.web_queue_job "):
            job_id = str(args.get("job_id", ""))
            row = {
                "job_id": job_id,
                "conversation_id": str(args.get("conversation_id", "")),
                "sender": str(args.get("sender", "")),
                "message_type": str(args.get("message_type", "")),
                "payload": self._payload(args.get("payload")),
                "status": str(args.get("status", "pending")),
                "attempts": int(args.get("attempts") or 0),
                "lease_expires_at": args.get("lease_expires_at"),
                "error_message": args.get("error_message"),
                "completed_at": args.get("completed_at"),
                "client_message_id": args.get("client_message_id"),
                "created_at": args.get("created_at") or now,
                "updated_at": args.get("updated_at") or now,
            }
            self._state.queue_jobs[job_id] = row
            return _MemoryResult(rowcount=1)

        if (
            "update mugen.web_queue_job set status = 'pending', lease_expires_at = null, updated_at = now() "
            in sql
            and "where status = 'processing'" in sql
        ):
            boundary = args.get("now_ts")
            if boundary is None:
                boundary = now
            updated = 0
            for row in self._state.queue_jobs.values():
                if str(row.get("status", "")).strip().lower() != "processing":
                    continue
                lease_expires_at = row.get("lease_expires_at")
                if lease_expires_at is None or lease_expires_at <= boundary:
                    row["status"] = "pending"
                    row["lease_expires_at"] = None
                    row["updated_at"] = now
                    updated += 1
            return _MemoryResult(rowcount=updated)

        if (
            "from mugen.web_queue_job where status = 'pending'" in sql
            and "for update skip locked" in sql
        ):
            pending_rows = sorted(
                (
                    dict(row)
                    for row in self._state.queue_jobs.values()
                    if str(row.get("status", "")).strip().lower() == "pending"
                ),
                key=lambda row: row.get("created_at") or now,
            )
            return _MemoryResult(rows=pending_rows[:1])

        if (
            sql.startswith("update mugen.web_queue_job set status = :status,")
            and "returning job_id" in sql
        ):
            job_id = str(args.get("job_id", ""))
            row = self._state.queue_jobs.get(job_id)
            if row is None:
                return _MemoryResult(rows=[], rowcount=0)
            row["status"] = args.get("status")
            row["attempts"] = int(args.get("attempts") or 0)
            row["updated_at"] = args.get("updated_at") or now
            row["lease_expires_at"] = args.get("lease_expires_at")
            row["error_message"] = args.get("error_message")
            row["completed_at"] = args.get("completed_at")
            return _MemoryResult(rows=[dict(row)], rowcount=1)

        if sql.startswith("select status, attempts from mugen.web_queue_job where job_id = :job_id"):
            row = self._queue_row(str(args.get("job_id", "")))
            return _MemoryResult(rows=[] if row is None else [row])

        if sql.startswith("update mugen.web_queue_job set lease_expires_at = :lease_expires_at"):
            job_id = str(args.get("job_id", ""))
            row = self._state.queue_jobs.get(job_id)
            if row is None:
                return _MemoryResult(rowcount=0)
            if str(row.get("status", "")).strip().lower() != str(
                args.get("current_status", "")
            ).strip().lower():
                return _MemoryResult(rowcount=0)
            expected = args.get("expected_attempt")
            if expected is not None and int(row.get("attempts") or 0) != int(expected):
                return _MemoryResult(rowcount=0)
            row["lease_expires_at"] = args.get("lease_expires_at")
            row["updated_at"] = args.get("updated_at") or now
            return _MemoryResult(rowcount=1)

        if (
            sql.startswith("select job_id, conversation_id, sender, message_type, payload, status, attempts,")
            and "from mugen.web_queue_job where job_id = :job_id" in sql
        ):
            row = self._queue_row(str(args.get("job_id", "")))
            return _MemoryResult(rows=[] if row is None else [row])

        if (
            sql.startswith("update mugen.web_queue_job set status = :status,")
            and "error_message = :error_message, completed_at = :completed_at where job_id = :job_id"
            in sql
        ):
            job_id = str(args.get("job_id", ""))
            row = self._state.queue_jobs.get(job_id)
            if row is None:
                return _MemoryResult(rowcount=0)
            if "and status = :current_status" in sql:
                if str(row.get("status", "")).strip().lower() != str(
                    args.get("current_status", "")
                ).strip().lower():
                    return _MemoryResult(rowcount=0)
                if int(row.get("attempts") or 0) != int(args.get("expected_attempt") or 0):
                    return _MemoryResult(rowcount=0)
            row["status"] = args.get("status")
            row["lease_expires_at"] = None
            row["updated_at"] = args.get("updated_at") or now
            row["error_message"] = args.get("error_message")
            row["completed_at"] = args.get("completed_at")
            return _MemoryResult(rowcount=1)

        if sql == "delete from mugen.web_queue_job":
            count = len(self._state.queue_jobs)
            self._state.queue_jobs.clear()
            return _MemoryResult(rowcount=count)

        if (
            sql.startswith("select job_id, conversation_id, sender, message_type, payload, status, attempts,")
            and "from mugen.web_queue_job order by created_at asc" in sql
        ):
            rows = sorted(
                [dict(row) for row in self._state.queue_jobs.values()],
                key=lambda row: row.get("created_at") or now,
            )
            return _MemoryResult(rows=rows)

        if sql.startswith("select payload from mugen.web_queue_job where status in ('pending', 'processing')"):
            rows = [
                {"payload": dict(row.get("payload") or {})}
                for row in self._state.queue_jobs.values()
                if str(row.get("status", "")).strip().lower() in {"pending", "processing"}
            ]
            return _MemoryResult(rows=rows)

        if sql.startswith("select to_regclass('mugen.web_queue_job') as web_queue_job,"):
            return _MemoryResult(
                rows=[
                    {
                        "web_queue_job": "mugen.web_queue_job",
                        "web_conversation_state": "mugen.web_conversation_state",
                        "web_conversation_event": "mugen.web_conversation_event",
                        "web_media_token": "mugen.web_media_token",
                    }
                ]
            )

        if sql.startswith(
            "select token, owner_user_id, file_path, mime_type, filename, expires_at from mugen.web_media_token where token = :token"
        ):
            token = str(args.get("token", ""))
            row = self._state.media_tokens.get(token)
            return _MemoryResult(rows=[] if row is None else [dict(row)])

        if sql.startswith("delete from mugen.web_media_token where token = :token"):
            token = str(args.get("token", ""))
            removed = self._state.media_tokens.pop(token, None)
            return _MemoryResult(rowcount=1 if removed is not None else 0)

        if sql.startswith("insert into mugen.web_media_token "):
            token = str(args.get("token", ""))
            self._state.media_tokens[token] = {
                "token": token,
                "owner_user_id": args.get("owner_user_id"),
                "conversation_id": args.get("conversation_id"),
                "file_path": args.get("file_path"),
                "mime_type": args.get("mime_type"),
                "filename": args.get("filename"),
                "expires_at": args.get("expires_at"),
                "created_at": now,
                "updated_at": now,
            }
            return _MemoryResult(rowcount=1)

        if sql.startswith("select token, file_path, expires_at from mugen.web_media_token"):
            return _MemoryResult(rows=[dict(row) for row in self._state.media_tokens.values()])

        if sql.startswith(
            "select owner_user_id from mugen.web_conversation_state where conversation_id = :conversation_id"
        ):
            conversation_id = str(args.get("conversation_id", ""))
            row = self._state.conversation_states.get(conversation_id)
            if row is None:
                return _MemoryResult(rows=[])
            return _MemoryResult(rows=[{"owner_user_id": row.get("owner_user_id")}])

        if (
            sql.startswith("select owner_user_id, stream_generation, next_event_id from mugen.web_conversation_state")
            and "where conversation_id = :conversation_id" in sql
        ):
            conversation_id = str(args.get("conversation_id", ""))
            row = self._state.conversation_states.get(conversation_id)
            return _MemoryResult(rows=[] if row is None else [dict(row)])

        if sql.startswith("select stream_generation, stream_version, next_event_id from mugen.web_conversation_state"):
            conversation_id = str(args.get("conversation_id", ""))
            row = self._state.conversation_states.get(conversation_id)
            if row is None:
                return _MemoryResult(rows=[])
            return _MemoryResult(
                rows=[
                    {
                        "stream_generation": row.get("stream_generation"),
                        "stream_version": row.get("stream_version"),
                        "next_event_id": row.get("next_event_id"),
                    }
                ]
            )

        if sql.startswith(
            "select stream_generation from mugen.web_conversation_state where conversation_id = :conversation_id"
        ):
            conversation_id = str(args.get("conversation_id", ""))
            row = self._state.conversation_states.get(conversation_id)
            if row is None:
                return _MemoryResult(rows=[])
            return _MemoryResult(
                rows=[{"stream_generation": row.get("stream_generation")}]
            )

        if sql.startswith("insert into mugen.web_conversation_state "):
            conversation_id = str(args.get("conversation_id", ""))
            owner_user_id = args.get("owner_user_id")
            if owner_user_id in [None, ""]:
                owner_user_id = "system"
            next_event_id = int(args.get("next_event_id") or 1)
            if conversation_id not in self._state.conversation_states:
                self._state.conversation_states[conversation_id] = {
                    "conversation_id": conversation_id,
                    "owner_user_id": owner_user_id,
                    "stream_generation": args.get("stream_generation"),
                    "stream_version": args.get("stream_version"),
                    "next_event_id": next_event_id,
                    "created_at": now,
                    "updated_at": now,
                }
                return _MemoryResult(rowcount=1)
            if "on conflict (conversation_id) do update" in sql:
                row = self._state.conversation_states[conversation_id]
                row["stream_generation"] = args.get("stream_generation")
                row["stream_version"] = args.get("stream_version")
                row["next_event_id"] = next_event_id
                row["updated_at"] = now
                return _MemoryResult(rowcount=1)
            return _MemoryResult(rowcount=0)

        if sql.startswith("update mugen.web_conversation_state set next_event_id = :next_event_id"):
            conversation_id = str(args.get("conversation_id", ""))
            row = self._state.conversation_states.get(conversation_id)
            if row is None:
                return _MemoryResult(rowcount=0)
            row["next_event_id"] = int(args.get("next_event_id") or 1)
            row["stream_generation"] = args.get("stream_generation")
            row["stream_version"] = args.get("stream_version")
            row["updated_at"] = now
            return _MemoryResult(rowcount=1)

        if sql.startswith("delete from mugen.web_conversation_event where conversation_id = :conversation_id and event_id < :min_keep_event_id"):
            conversation_id = str(args.get("conversation_id", ""))
            min_keep_event_id = int(args.get("min_keep_event_id") or 1)
            events = self._state.conversation_events.get(conversation_id, {})
            removed = 0
            for event_id in list(events):
                if int(event_id) < min_keep_event_id:
                    del events[event_id]
                    removed += 1
            return _MemoryResult(rowcount=removed)

        if sql.startswith("delete from mugen.web_conversation_event where conversation_id = :conversation_id"):
            conversation_id = str(args.get("conversation_id", ""))
            removed = len(self._state.conversation_events.get(conversation_id, {}))
            self._state.conversation_events[conversation_id] = {}
            return _MemoryResult(rowcount=removed)

        if sql.startswith("insert into mugen.web_conversation_event "):
            conversation_id = str(args.get("conversation_id", ""))
            event_id = int(args.get("event_id") or 0)
            if event_id <= 0:
                return _MemoryResult(rowcount=0)
            payload = self._payload(args.get("payload"))
            events = self._state.conversation_events.setdefault(conversation_id, {})
            if event_id in events and "on conflict (conversation_id, event_id) do update" not in sql:
                return _MemoryResult(rowcount=0)
            events[event_id] = {
                "conversation_id": conversation_id,
                "event_id": event_id,
                "event_type": str(args.get("event_type", "system")),
                "payload": payload,
                "stream_generation": args.get("stream_generation"),
                "stream_version": int(args.get("stream_version") or 1),
                "created_at": args.get("created_at") or now,
                "updated_at": now,
            }
            return _MemoryResult(rowcount=1)

        if sql.startswith(
            "select event_id, event_type, payload, created_at, stream_generation, stream_version from mugen.web_conversation_event where conversation_id = :conversation_id order by event_id desc limit :event_limit"
        ):
            conversation_id = str(args.get("conversation_id", ""))
            limit = int(args.get("event_limit") or 100)
            events = self._state.conversation_events.get(conversation_id, {})
            rows = [
                dict(events[event_id])
                for event_id in sorted(events, reverse=True)[:limit]
            ]
            return _MemoryResult(rows=rows)

        if sql.startswith(
            "select event_id, event_type, payload, created_at, stream_generation, stream_version from mugen.web_conversation_event where conversation_id = :conversation_id and stream_generation = :stream_generation and event_id > :after_event_id order by event_id asc limit :limit"
        ):
            conversation_id = str(args.get("conversation_id", ""))
            stream_generation = args.get("stream_generation")
            after_event_id = int(args.get("after_event_id") or 0)
            limit = int(args.get("limit") or 100)
            events = self._state.conversation_events.get(conversation_id, {})
            rows = []
            for event_id in sorted(events):
                row = events[event_id]
                if row.get("stream_generation") != stream_generation:
                    continue
                if int(event_id) <= after_event_id:
                    continue
                rows.append(dict(row))
                if len(rows) >= limit:
                    break
            return _MemoryResult(rows=rows)

        raise AssertionError(f"Unhandled SQL in in-memory relational session: {sql}")


class _InMemoryWebRelationalGateway:
    def __init__(self) -> None:
        self._state = _InMemoryWebRelationalState()

    @asynccontextmanager
    async def raw_session(self):
        yield _InMemoryWebRelationalSession(self._state)

    async def check_readiness(self):
        return None


class _SequenceMappings:
    def __init__(self, rows):
        self._rows = list(rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        if not self._rows:
            raise AssertionError("expected one row")
        return self._rows[0]

    def all(self):
        return list(self._rows)


class _SequenceResult:
    def __init__(
        self,
        *,
        rows=None,
        scalar_value=None,
        first_value=None,
        fetchall_rows=None,
    ):
        self._rows = list(rows or [])
        self._scalar_value = scalar_value
        self._first_value = first_value
        self._fetchall_rows = list(fetchall_rows or [])

    def mappings(self):
        return _SequenceMappings(self._rows)

    def scalar(self):
        return self._scalar_value

    def first(self):
        if self._first_value is not None:
            return self._first_value
        if self._rows:
            return self._rows[0]
        return None

    def fetchall(self):
        if self._fetchall_rows:
            return list(self._fetchall_rows)
        return list(self._rows)


class _SequenceSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        args = dict(params or {})
        self.calls.append((sql, args))
        if not self._responses:
            raise AssertionError(f"Unexpected SQL call: {sql}")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(sql, args)
        return response


class _HeartbeatTaskDouble:
    def __init__(
        self,
        *,
        done_sequence: list[bool],
        result_value=None,
        await_cancelled: bool = False,
    ) -> None:
        self._done_sequence = list(done_sequence)
        self._result_value = result_value
        self._await_cancelled = await_cancelled

    def done(self) -> bool:
        if self._done_sequence:
            return self._done_sequence.pop(0)
        return True

    def result(self):
        if isinstance(self._result_value, BaseException):
            raise self._result_value
        return self._result_value

    def __await__(self):
        async def _wait():
            if self._await_cancelled:
                raise asyncio.CancelledError()
            return None

        return _wait().__await__()


def _force_relational_session(client: DefaultWebClient, session: _SequenceSession) -> None:
    @asynccontextmanager
    async def _session_cm():
        yield session

    runtime_store = client._web_runtime_store  # pylint: disable=protected-access
    if runtime_store is not None:
        runtime_store._relational_session = _session_cm  # type: ignore[attr-defined]  # pylint: disable=protected-access


def _build_config(*, basedir: str, replay_max_events: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        basedir=basedir,
        rdbms=SimpleNamespace(
            migration_tracks=SimpleNamespace(
                core=SimpleNamespace(schema="mugen"),
            )
        ),
        web=SimpleNamespace(
            sse=SimpleNamespace(
                keepalive_seconds=1,
                replay_max_events=replay_max_events,
                enqueue_timeout_seconds=0.01,
                cross_instance_poll_seconds=0.1,
            ),
            queue=SimpleNamespace(
                poll_interval_seconds=0.05,
                processing_lease_seconds=1,
                max_pending_jobs=100,
            ),
            media=SimpleNamespace(
                backend="object",
                storage=SimpleNamespace(path="web_media"),
                object=SimpleNamespace(
                    cache_path="web_media_object_cache",
                    key_prefix="web:media:object",
                ),
                max_upload_bytes=1024 * 1024,
                max_attachments_per_message=10,
                allowed_mimetypes=["image/*", "application/*", "text/*"],
                download_token_ttl_seconds=10,
                retention_seconds=1,
            ),
        ),
    )


def _build_runtime_store(
    *,
    config: SimpleNamespace,
    relational_storage_gateway,
    logging_gateway,
) -> RelationalWebRuntimeStore:
    class _SessionMaker:
        def __call__(self):
            return relational_storage_gateway.raw_session()

    runtime = SimpleNamespace(engine=None, session_maker=_SessionMaker())
    return RelationalWebRuntimeStore(
        config=config,
        logging_gateway=logging_gateway,
        relational_runtime=runtime,
    )


def _build_media_gateway(
    *,
    config: SimpleNamespace,
    keyval_storage_gateway,
    logging_gateway,
):
    return DefaultMediaStorageGateway(
        config=config,
        keyval_storage_gateway=keyval_storage_gateway,
        logging_gateway=logging_gateway,
    )


class TestDefaultWebClient(unittest.IsolatedAsyncioTestCase):
    """Covers durable queue, replay, and media token behavior."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.keyval = _InMemoryKeyVal()
        self.relational = _InMemoryWebRelationalGateway()
        self.logger = Mock()
        self.config = _build_config(basedir=self.tmpdir.name)
        self.messaging = SimpleNamespace(
            handle_text_message=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            handle_audio_message=AsyncMock(return_value=[]),
            handle_video_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_composed_message=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
        )

        self.client = DefaultWebClient(
            config=self.config,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=self.config,
                keyval_storage_gateway=self.keyval,
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=self.config,
                relational_storage_gateway=self.relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.tmpdir.cleanup()

    async def _next_non_ping(self, stream, *, attempts: int = 10) -> str:
        for _ in range(attempts):
            chunk = await stream.__anext__()
            if chunk != ": ping\n\n":
                return chunk
        self.fail("Timed out waiting for non-ping SSE chunk.")

    def test_init_defaults_media_backend_to_object_when_unset(self) -> None:
        config = _build_config(basedir=self.tmpdir.name)
        config.web.media.backend = None
        client = DefaultWebClient(
            config=config,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=config,
                keyval_storage_gateway=self.keyval,
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=config,
                relational_storage_gateway=self.relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        self.assertTrue(client._media_storage_path.endswith("web_media"))  # pylint: disable=protected-access

    def test_init_rejects_non_object_media_backend(self) -> None:
        config = _build_config(basedir=self.tmpdir.name)
        config.web.media.backend = "filesystem"
        with self.assertRaisesRegex(
            ValueError,
            "web.media.backend must be 'object'",
        ):
            DefaultWebClient(
                config=config,
                ipc_service=Mock(),
                media_storage_gateway=_build_media_gateway(
                    config=config,
                    keyval_storage_gateway=self.keyval,
                    logging_gateway=self.logger,
                ),
                web_runtime_store=_build_runtime_store(
                    config=config,
                    relational_storage_gateway=self.relational,
                    logging_gateway=self.logger,
                ),
                logging_gateway=self.logger,
                messaging_service=self.messaging,
                user_service=Mock(),
            )

    def test_init_rejects_non_object_media_backend_in_client_guard(self) -> None:
        config = _build_config(basedir=self.tmpdir.name)
        config.web.media.backend = "filesystem"
        with self.assertRaisesRegex(
            RuntimeError,
            "web.media.backend must be 'object'",
        ):
            DefaultWebClient(
                config=config,
                ipc_service=Mock(),
                media_storage_gateway=Mock(),
                web_runtime_store=_build_runtime_store(
                    config=config,
                    relational_storage_gateway=self.relational,
                    logging_gateway=self.logger,
                ),
                logging_gateway=self.logger,
                messaging_service=self.messaging,
                user_service=Mock(),
            )

    async def test_queue_enqueue_and_process_text_message(self) -> None:
        payload = await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-1",
            message_type="text",
            text="hello",
            client_message_id="m-1",
        )

        self.assertEqual(payload["conversation_id"], "conv-1")

        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)

        await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        self.messaging.handle_text_message.assert_awaited_once()

        async with self.client._storage_lock:  # pylint: disable=protected-access
            queue = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            self.assertEqual(queue["jobs"][0]["status"], "done")
            events = await self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-1",
                last_event_id=None,
            )

        self.assertEqual(events[0]["event"], "ack")
        self.assertEqual(events[1]["event"], "thinking")
        self.assertEqual(events[1]["data"]["signal"], "thinking")
        self.assertEqual(events[1]["data"]["state"], "start")
        self.assertEqual(events[2]["event"], "message")
        self.assertEqual(events[3]["event"], "thinking")
        self.assertEqual(events[3]["data"]["signal"], "thinking")
        self.assertEqual(events[3]["data"]["state"], "stop")
        self.assertGreater(self.client.media_max_upload_bytes, 0)

    async def test_object_media_backend_roundtrip(self) -> None:
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.backend = "object"
        relational = _InMemoryWebRelationalGateway()
        logger = Mock()
        client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=relational,
                logging_gateway=logger,
            ),
            logging_gateway=logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        media_ref = await client._resolve_media_source_path(  # pylint: disable=protected-access
            file_path=b"payload",
            filename="payload.bin",
        )
        self.assertTrue(isinstance(media_ref, str) and media_ref.startswith("object:"))
        materialized = await client._materialize_media_reference(media_ref)  # pylint: disable=protected-access
        self.assertTrue(isinstance(materialized, str) and os.path.exists(materialized))
        await client.close()

    async def test_object_backend_persists_composed_attachment_refs(self) -> None:
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.backend = "object"
        relational = _InMemoryWebRelationalGateway()
        logger = Mock()
        client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=relational,
                logging_gateway=logger,
            ),
            logging_gateway=logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        media_file = Path(self.tmpdir.name) / "composed-upload.txt"
        media_file.write_text("payload", encoding="utf-8")
        await client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-obj",
            message_type="composed",
            metadata={
                "composition_mode": "message_with_attachments",
                "parts": [{"type": "attachment", "id": "a1"}],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": str(media_file),
                        "mime_type": "text/plain",
                        "original_filename": "composed-upload.txt",
                    }
                ],
            },
            client_message_id="cid-obj",
        )
        claimed = await client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        attachment_ref = claimed["metadata"]["attachments"][0]["file_path"]
        self.assertTrue(isinstance(attachment_ref, str) and attachment_ref.startswith("object:"))
        materialized = await client._materialize_media_reference(attachment_ref)  # pylint: disable=protected-access
        self.assertTrue(isinstance(materialized, str) and os.path.exists(materialized))
        await client.close()

    async def test_resolve_media_source_path_keeps_existing_object_refs(self) -> None:
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.backend = "object"
        relational = _InMemoryWebRelationalGateway()
        logger = Mock()
        client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=relational,
                logging_gateway=logger,
            ),
            logging_gateway=logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        stored_ref = await client._media_storage_gateway.store_bytes(  # pylint: disable=protected-access
            b"payload",
            filename_hint="x.bin",
        )

        resolved_ref = await client._resolve_media_source_path(  # pylint: disable=protected-access
            file_path=stored_ref,
            filename="x.bin",
        )

        self.assertEqual(resolved_ref, stored_ref)
        materialized = await client._materialize_media_reference(  # pylint: disable=protected-access
            resolved_ref
        )
        self.assertTrue(isinstance(materialized, str) and os.path.exists(materialized))
        await client.close()

    async def test_invalid_media_backend_raises(self) -> None:
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.backend = "bad-backend"
        with self.assertRaisesRegex(ValueError, "web.media.backend must be 'object'"):
            relational = _InMemoryWebRelationalGateway()
            logger = Mock()
            DefaultWebClient(
                config=cfg,
                ipc_service=Mock(),
                media_storage_gateway=_build_media_gateway(
                    config=cfg,
                    keyval_storage_gateway=_InMemoryKeyVal(),
                    logging_gateway=logger,
                ),
                web_runtime_store=_build_runtime_store(
                    config=cfg,
                    relational_storage_gateway=relational,
                    logging_gateway=logger,
                ),
                logging_gateway=logger,
                messaging_service=self.messaging,
                user_service=Mock(),
            )

    async def test_media_reference_helper_branches(self) -> None:
        mocked_gateway = SimpleNamespace(
            exists=AsyncMock(side_effect=[False, True]),
            store_file=AsyncMock(return_value=None),
            store_bytes=AsyncMock(return_value=None),
            materialize=AsyncMock(return_value=os.path.abspath("relative/path")),
            cleanup=AsyncMock(),
            init=AsyncMock(),
            close=AsyncMock(),
        )
        self.client._media_storage_gateway = mocked_gateway  # pylint: disable=protected-access
        resolved = await self.client._resolve_media_source_path(  # pylint: disable=protected-access
            file_path="relative/path",
            filename="x.bin",
        )
        self.assertEqual(resolved, os.path.abspath("relative/path"))

        with patch.object(
            self.client,
            "_resolve_media_source_path",
            AsyncMock(return_value=None),
        ):
            self.assertIsNone(
                await self.client._persist_media_reference(  # pylint: disable=protected-access
                    file_path="x",
                    filename_hint="x.bin",
                )
            )

        temp_file = os.path.join(self.tmpdir.name, "remove-me.bin")
        with open(temp_file, "wb") as handle:
            handle.write(b"payload")
        with (
            patch.object(
                self.client,
                "_resolve_media_source_path",
                AsyncMock(return_value="object:abc"),
            ),
            patch("os.remove", side_effect=OSError()),
        ):
            persisted = await self.client._persist_media_reference(  # pylint: disable=protected-access
                file_path=temp_file,
                filename_hint="x.bin",
            )
        self.assertEqual(persisted, "object:abc")

        self.assertIsNone(
            await self.client._materialize_media_reference(None)  # pylint: disable=protected-access
        )

        metadata = {"attachments": "bad"}
        returned = await self.client._persist_composed_media_references(metadata)  # pylint: disable=protected-access
        self.assertEqual(returned, metadata)

        with self.assertRaises(ValueError):
            await self.client._persist_composed_media_references(  # pylint: disable=protected-access
                {"attachments": [123]}
            )

        with patch.object(
            self.client,
            "_persist_media_reference",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(ValueError):
                await self.client._persist_composed_media_references(  # pylint: disable=protected-access
                    {"attachments": [{"file_path": "/tmp/nope"}]}
                )

        self.assertEqual(
            self.client._infer_media_extension("IMAGE.PNG"),  # pylint: disable=protected-access
            ".png",
        )

    async def test_resolve_media_source_path_imports_external_file_into_managed_storage(
        self,
    ) -> None:
        external_path = os.path.join(self.tmpdir.name, "external-upload.bin")
        with open(external_path, "wb") as handle:
            handle.write(b"payload")

        self.assertIsNone(
            await self.client._media_storage_gateway.materialize(external_path)  # pylint: disable=protected-access
        )
        managed_ref = await self.client._resolve_media_source_path(  # pylint: disable=protected-access
            file_path=external_path,
            filename="external-upload.bin",
        )
        self.assertIsInstance(managed_ref, str)
        self.assertNotEqual(os.path.abspath(external_path), managed_ref)
        self.assertTrue(await self.client._media_storage_gateway.exists(managed_ref))  # pylint: disable=protected-access

    async def test_persist_media_reference_does_not_delete_external_source_file(self) -> None:
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.backend = "object"
        relational = _InMemoryWebRelationalGateway()
        logger = Mock()
        client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=relational,
                logging_gateway=logger,
            ),
            logging_gateway=logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        external_path = os.path.join(self.tmpdir.name, "external-source.bin")
        with open(external_path, "wb") as handle:
            handle.write(b"payload")

        persisted_ref = await client._persist_media_reference(  # pylint: disable=protected-access
            file_path=external_path,
            filename_hint="external-source.bin",
        )

        self.assertTrue(isinstance(persisted_ref, str) and persisted_ref.startswith("object:"))
        self.assertTrue(os.path.exists(external_path))
        await client.close()

    async def test_persist_media_reference_cleans_up_managed_upload_path(self) -> None:
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.backend = "object"
        relational = _InMemoryWebRelationalGateway()
        logger = Mock()
        client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=relational,
                logging_gateway=logger,
            ),
            logging_gateway=logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        os.makedirs(client._media_storage_path, exist_ok=True)  # pylint: disable=protected-access
        managed_path = os.path.join(client._media_storage_path, "managed-upload.bin")  # pylint: disable=protected-access
        with open(managed_path, "wb") as handle:
            handle.write(b"payload")

        persisted_ref = await client._persist_media_reference(  # pylint: disable=protected-access
            file_path=managed_path,
            filename_hint="managed-upload.bin",
        )

        self.assertTrue(isinstance(persisted_ref, str) and persisted_ref.startswith("object:"))
        self.assertFalse(os.path.exists(managed_path))
        await client.close()

    async def test_persist_media_reference_skips_cleanup_for_missing_source_path(self) -> None:
        missing_path = os.path.join(self.tmpdir.name, "missing-source.bin")
        with patch.object(
            self.client,
            "_resolve_media_source_path",
            new=AsyncMock(return_value="object:missing"),
        ):
            persisted = await self.client._persist_media_reference(  # pylint: disable=protected-access
                file_path=missing_path,
                filename_hint="missing-source.bin",
            )
        self.assertEqual(persisted, "object:missing")

    async def test_persist_media_reference_logs_warning_when_managed_cleanup_fails(
        self,
    ) -> None:
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.backend = "object"
        client_logger = Mock()
        relational = _InMemoryWebRelationalGateway()
        client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=client_logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=relational,
                logging_gateway=client_logger,
            ),
            logging_gateway=client_logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        os.makedirs(client._media_storage_path, exist_ok=True)  # pylint: disable=protected-access
        managed_path = os.path.join(client._media_storage_path, "managed-fail.bin")  # pylint: disable=protected-access
        with open(managed_path, "wb") as handle:
            handle.write(b"payload")

        with patch("os.remove", side_effect=OSError("denied")):
            persisted = await client._persist_media_reference(  # pylint: disable=protected-access
                file_path=managed_path,
                filename_hint="managed-fail.bin",
            )

        self.assertTrue(isinstance(persisted, str) and persisted.startswith("object:"))
        client_logger.warning.assert_called_once()
        self.assertIn(
            "Failed to cleanup managed media upload path",
            str(client_logger.warning.call_args.args[0]),
        )
        await client.close()

    async def test_resolve_managed_upload_cleanup_path_branch_coverage(self) -> None:
        self.assertIsNone(
            self.client._resolve_managed_upload_cleanup_path("   ")  # pylint: disable=protected-access
        )

        with patch("mugen.core.client.web.Path.resolve", side_effect=OSError()):
            self.assertIsNone(
                self.client._resolve_managed_upload_cleanup_path(  # pylint: disable=protected-access
                    "/tmp/example.bin"
                )
            )

        media_dir = Path(self.client._media_storage_path)  # pylint: disable=protected-access
        media_dir.mkdir(parents=True, exist_ok=True)
        self.assertIsNone(
            self.client._resolve_managed_upload_cleanup_path(  # pylint: disable=protected-access
                str(media_dir)
            )
        )

    async def test_mark_job_status_else_branch_and_close_error_swallow(self) -> None:
        payload = await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-mark",
            message_type="text",
            text="hello",
            client_message_id="cid-mark",
        )
        await self.client._mark_job_status(  # pylint: disable=protected-access
            payload["job_id"],
            status="processing",
            error="still-running",
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            queue_state = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
        self.assertEqual(queue_state["jobs"][0]["status"], "processing")
        self.assertEqual(queue_state["jobs"][0]["error"], "still-running")

        self.client._media_storage_gateway.close = AsyncMock(  # pylint: disable=protected-access
            side_effect=RuntimeError("boom")
        )
        await self.client.close()

    async def test_mark_job_done_skips_invalid_terminal_transition_for_keyval(self) -> None:
        payload = await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-invalid-transition",
            message_type="text",
            text="hello",
            client_message_id="cid-invalid-terminal",
        )

        self.logger.reset_mock()
        await self.client._mark_job_done(payload["job_id"])  # pylint: disable=protected-access

        async with self.client._storage_lock:  # pylint: disable=protected-access
            queue_state = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
        self.assertEqual(queue_state["jobs"][0]["status"], "pending")
        self.logger.warning.assert_called_once()
        self.assertIn(
            "violates lifecycle invariant",
            str(self.logger.warning.call_args.args[0]),
        )

    async def test_mark_job_done_skips_attempt_mismatch_for_keyval(self) -> None:
        payload = await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-attempt-mismatch",
            message_type="text",
            text="hello",
            client_message_id="cid-attempt-mismatch",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["status"], "processing")

        self.logger.reset_mock()
        await self.client._mark_job_done(  # pylint: disable=protected-access
            payload["job_id"],
            expected_attempt=int(claimed["attempts"]) + 1,
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            queue_state = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
        self.assertEqual(queue_state["jobs"][0]["status"], "processing")
        self.assertEqual(queue_state["jobs"][0]["attempts"], int(claimed["attempts"]))
        self.logger.warning.assert_called_once()
        self.assertIn(
            "precondition mismatch",
            str(self.logger.warning.call_args.args[0]),
        )

    async def test_ensure_media_directory_creates_storage_path(self) -> None:
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.backend = "object"
        cfg.web.media.storage.path = "object-media-path"
        relational = _InMemoryWebRelationalGateway()
        logger = Mock()
        client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=relational,
                logging_gateway=logger,
            ),
            logging_gateway=logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        client._ensure_media_directory()  # pylint: disable=protected-access
        expected_media_path = Path(self.tmpdir.name) / "object-media-path"
        self.assertTrue(expected_media_path.exists())
        await client.close()

    async def test_queue_enqueue_and_process_file_message(self) -> None:
        media_file = Path(self.tmpdir.name) / "upload.txt"
        media_file.write_text("payload", encoding="utf-8")

        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-2",
            message_type="file",
            file_path=str(media_file),
            mime_type="text/plain",
            original_filename="upload.txt",
        )

        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        self.messaging.handle_file_message.assert_awaited_once()
        kwargs = self.messaging.handle_file_message.await_args.kwargs
        self.assertEqual(kwargs["platform"], "web")
        self.assertEqual(kwargs["room_id"], "conv-2")
        self.assertEqual(kwargs["sender"], "user-1")

    async def test_emit_thinking_signal_warns_when_append_event_fails(self) -> None:
        self.client._append_event = AsyncMock(  # pylint: disable=protected-access
            side_effect=RuntimeError("append boom")
        )

        await self.client._emit_thinking_signal(  # pylint: disable=protected-access
            conversation_id="conv-1",
            job_id="job-1",
            client_message_id="client-1",
            sender="user-1",
            state="start",
        )

        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any("Failed to emit web thinking signal" in message for message in warning_messages)
        )

    async def test_process_claimed_job_logs_when_messaging_returns_no_responses(self) -> None:
        self.messaging.handle_text_message = AsyncMock(return_value=[])

        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-noresp",
            message_type="text",
            text="hello",
            client_message_id="cid-noresp",
        )

        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "fallback 'No response generated.' emitted" in message
                and "messaging service returned no responses" in message
                and "reason=empty-list" in message
                and "conversation_id=conv-noresp" in message
                and "client_message_id=cid-noresp" in message
                and "message_type=text" in message
                for message in warning_messages
            )
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            events = await self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-noresp",
                last_event_id=None,
            )

        system_events = [event for event in events if event["event"] == "system"]
        self.assertEqual(len(system_events), 1)
        self.assertEqual(system_events[0]["data"]["message"], "No response generated.")

    async def test_process_claimed_job_logs_when_text_response_is_blank(self) -> None:
        self.messaging.handle_text_message = AsyncMock(
            return_value=[{"type": "text", "content": None}]
        )

        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-blank",
            message_type="text",
            text="hello",
            client_message_id="cid-blank",
        )

        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "fallback 'No response generated.' emitted" in message
                and "blank text response content" in message
                and "conversation_id=conv-blank" in message
                and "client_message_id=cid-blank" in message
                and "response_index=0" in message
                and "content_type=NoneType" in message
                for message in warning_messages
            )
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            events = await self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-blank",
                last_event_id=None,
            )

        message_events = [event for event in events if event["event"] == "message"]
        self.assertEqual(len(message_events), 1)
        self.assertEqual(
            message_events[0]["data"]["message"]["content"],
            "No response generated.",
        )

    async def test_conversation_ownership_enforced(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-own",
            message_type="text",
            text="hello",
        )

        with self.assertRaises(PermissionError):
            await self.client.enqueue_message(
                auth_user="user-2",
                conversation_id="conv-own",
                message_type="text",
                text="hello",
            )

    async def test_enqueue_validation_and_queue_limit_branches(self) -> None:
        with self.assertRaises(ValueError):
            await self.client.enqueue_message(
                auth_user="user-1",
                conversation_id="conv-v",
                message_type="text",
                text="",
            )

        with self.assertRaises(ValueError):
            await self.client.enqueue_message(
                auth_user="user-1",
                conversation_id="conv-v",
                message_type="file",
                file_path=None,
            )

        with self.assertRaises(ValueError):
            await self.client.enqueue_message(
                auth_user="user-1",
                conversation_id="conv-v",
                message_type="text",
                text="ok",
                metadata=[],
            )

        with self.assertRaises(ValueError):
            await self.client.enqueue_message(
                auth_user="user-1",
                conversation_id="conv-v",
                message_type="composed",
                metadata={},
            )

        with self.assertRaises(ValueError):
            await self.client.enqueue_message(
                auth_user="user-1",
                conversation_id="conv-v",
                message_type="composed",
                metadata={
                    "composition_mode": "message_with_attachments",
                    "parts": [{"type": "attachment", "id": "a1"}],
                    "attachments": [],
                },
            )

        with self.assertRaises(ValueError):
            await self.client.enqueue_message(
                auth_user="user-1",
                conversation_id="conv-v",
                message_type="composed",
                metadata={
                    "composition_mode": "attachment_with_caption",
                    "parts": [{"type": "attachment", "id": "a1"}],
                    "attachments": [
                        {
                            "id": "a1",
                            "file_path": "/tmp/file.bin",
                            "mime_type": "application/octet-stream",
                            "metadata": {},
                            "caption": "",
                        }
                    ],
                },
            )

        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-v-meta",
            message_type="text",
            text="ok",
            metadata={"k": "v"},
        )

        self.client._queue_max_pending_jobs = 2  # pylint: disable=protected-access
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-v",
            message_type="text",
            text="first",
        )
        with self.assertRaises(OverflowError):
            await self.client.enqueue_message(
                auth_user="user-1",
                conversation_id="conv-v",
                message_type="text",
                text="second",
            )

        self.client._queue_max_pending_jobs = 100  # pylint: disable=protected-access
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-v-composed",
            message_type="composed",
            metadata={
                "composition_mode": "message_with_attachments",
                "parts": [{"type": "text", "text": "hello"}],
                "attachments": [],
            },
        )

    async def test_replay_ordering_and_truncation(self) -> None:
        cfg = _build_config(basedir=self.tmpdir.name, replay_max_events=2)
        relational = _InMemoryWebRelationalGateway()
        small_client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )

        await small_client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-r",
            message_type="text",
            text="first",
        )
        await small_client._append_event(  # pylint: disable=protected-access
            conversation_id="conv-r",
            event_type="system",
            data={"message": "two"},
        )
        await small_client._append_event(  # pylint: disable=protected-access
            conversation_id="conv-r",
            event_type="system",
            data={"message": "three"},
        )

        async with small_client._storage_lock:  # pylint: disable=protected-access
            events = await small_client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-r",
                last_event_id=None,
            )
            replay_after_first = await small_client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-r",
                last_event_id="2",
            )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["id"], "2")
        self.assertEqual(events[1]["id"], "3")
        self.assertEqual([event["id"] for event in replay_after_first], ["3"])

        await small_client.close()

    async def test_stale_processing_recovery(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-stale",
            message_type="text",
            text="hello",
        )

        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertEqual(claimed["status"], "processing")

        async with self.client._storage_lock:  # pylint: disable=protected-access
            queue = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            queue["jobs"][0]["status"] = "processing"
            queue["jobs"][0]["lease_expires_at"] = 0
            await self.client._write_queue_state_unlocked(queue)  # pylint: disable=protected-access
            await self.client._recover_stale_processing_jobs_unlocked()  # pylint: disable=protected-access
            queue = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access

        self.assertEqual(queue["jobs"][0]["status"], "pending")

    async def test_process_claimed_job_renews_processing_lease_while_active(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-lease-renew",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        self.client._queue_processing_lease_heartbeat_seconds = 0.01  # pylint: disable=protected-access

        async def _slow_dispatch(_job):
            await asyncio.sleep(0.05)
            return [{"type": "text", "content": "ok"}]

        with (
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(side_effect=_slow_dispatch),
            ),
            patch.object(
                self.client,
                "_renew_processing_lease",
                new=AsyncMock(return_value=True),
            ) as renew_lease,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        self.assertGreaterEqual(renew_lease.await_count, 1)

    async def test_claim_next_job_does_not_reclaim_active_processing_job(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-no-reclaim",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        self.client._queue_processing_lease_seconds = 0.3  # pylint: disable=protected-access
        self.client._queue_processing_lease_heartbeat_seconds = 0.05  # pylint: disable=protected-access

        async def _slow_dispatch(_job):
            await asyncio.sleep(0.5)
            return [{"type": "text", "content": "ok"}]

        with patch.object(
            self.client,
            "_dispatch_job_to_messaging",
            new=AsyncMock(side_effect=_slow_dispatch),
        ):
            worker_task = asyncio.create_task(
                self.client._process_claimed_job(claimed)  # pylint: disable=protected-access
            )
            await asyncio.sleep(0.35)
            reclaimed = await self.client._claim_next_job()  # pylint: disable=protected-access
            await worker_task

        self.assertIsNone(reclaimed)

    async def test_process_claimed_job_skips_terminal_side_effects_when_lease_lost(
        self,
    ) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-lease-lost",
            message_type="text",
            text="hello",
            client_message_id="cid-lease-lost",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)

        async def _slow_dispatch(_job):
            await asyncio.sleep(0.01)
            return [{"type": "text", "content": "ok"}]

        with (
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(side_effect=_slow_dispatch),
            ),
            patch.object(
                self.client,
                "_run_processing_lease_heartbeat",
                new=AsyncMock(return_value="lease_lost"),
            ),
            patch.object(
                self.client,
                "_mark_job_done",
                new=AsyncMock(),
            ) as mark_done,
            patch.object(
                self.client,
                "_mark_job_failed",
                new=AsyncMock(),
            ) as mark_failed,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_done.assert_not_awaited()
        mark_failed.assert_not_awaited()
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "Skipping web queue job side effects after lease loss" in message
                and "reason=lease_lost" in message
                for message in warning_messages
            )
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            events = await self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-lease-lost",
                last_event_id=None,
            )
        emitted_types = {event.get("event") for event in events}
        self.assertFalse(bool({"message", "system", "error"} & emitted_types))
        thinking_states = [
            str(event.get("data", {}).get("state"))
            for event in events
            if event.get("event") == "thinking"
        ]
        self.assertEqual(thinking_states, ["start"])

    async def test_process_claimed_job_skips_side_effects_when_owner_no_longer_matches(
        self,
    ) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-owner-lost",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)

        with (
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            ),
            patch.object(
                self.client,
                "_run_processing_lease_heartbeat",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                self.client,
                "_processing_owner_matches",
                new=AsyncMock(side_effect=[True, False, False]),
            ),
            patch.object(
                self.client,
                "_mark_job_done",
                new=AsyncMock(),
            ) as mark_done,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_done.assert_not_awaited()
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "Skipping web queue job side effects after lease loss" in message
                and "reason=lease_lost" in message
                for message in warning_messages
            )
        )

    async def test_process_claimed_job_skips_side_effects_when_owner_check_errors(
        self,
    ) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-owner-check-error",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)

        with (
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            ),
            patch.object(
                self.client,
                "_run_processing_lease_heartbeat",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                self.client,
                "_processing_owner_matches",
                new=AsyncMock(side_effect=RuntimeError("db unavailable")),
            ),
            patch.object(
                self.client,
                "_mark_job_done",
                new=AsyncMock(),
            ) as mark_done,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_done.assert_not_awaited()
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "Skipping web queue job side effects after lease loss" in message
                and "reason=lease_renew_failed" in message
                for message in warning_messages
            )
        )

    async def test_process_claimed_job_logs_final_lease_loss_when_stop_is_suppressed(
        self,
    ) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-final-loss",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)

        async def _loss_after_stop(*, job_id, stop_event, expected_attempt=None):
            _ = job_id
            _ = expected_attempt
            await stop_event.wait()
            return "lease_lost"

        with (
            patch.object(
                self.client,
                "_run_processing_lease_heartbeat",
                new=AsyncMock(side_effect=_loss_after_stop),
            ),
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            ),
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "stage=emit_processing_stop" in message and "reason=lease_lost" in message
                for message in warning_messages
            )
        )

    async def test_derive_queue_lease_heartbeat_seconds_handles_invalid_input(self) -> None:
        derived = self.client._derive_queue_lease_heartbeat_seconds("not-a-number")  # pylint: disable=protected-access
        self.assertEqual(derived, 1.0)

    async def test_renew_processing_lease_keyval_branches(self) -> None:
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
                {
                    "version": 1,
                    "jobs": [
                        {
                            "id": "other-job",
                            "status": "processing",
                            "attempts": 2,
                        },
                        {
                            "id": "target-job",
                            "status": "pending",
                            "attempts": 1,
                        },
                        {
                            "id": "processing-job",
                            "status": "processing",
                            "attempts": 3,
                        },
                    ],
                }
            )

        renewed_missing = await self.client._renew_processing_lease(  # pylint: disable=protected-access
            job_id="missing-job"
        )
        self.assertFalse(renewed_missing)

        renewed_pending = await self.client._renew_processing_lease(  # pylint: disable=protected-access
            job_id="target-job"
        )
        self.assertFalse(renewed_pending)

        renewed_mismatched_attempt = await self.client._renew_processing_lease(  # pylint: disable=protected-access
            job_id="processing-job",
            expected_attempt=2,
        )
        self.assertFalse(renewed_mismatched_attempt)

        renewed_matching_attempt = await self.client._renew_processing_lease(  # pylint: disable=protected-access
            job_id="processing-job",
            expected_attempt=3,
        )
        self.assertTrue(renewed_matching_attempt)

    async def test_renew_processing_lease_relational_branches(self) -> None:
        success_session = _SequenceSession([SimpleNamespace(rowcount=1)])
        _force_relational_session(self.client, success_session)
        renewed = await self.client._renew_processing_lease(  # pylint: disable=protected-access
            job_id="job-rel",
            expected_attempt=4,
        )
        self.assertTrue(renewed)
        sql, params = success_session.calls[0]
        self.assertIn("UPDATE mugen.web_queue_job", sql)
        self.assertEqual(params["job_id"], "job-rel")
        self.assertEqual(params["current_status"], "processing")
        self.assertEqual(params["expected_attempt"], 4)

        failure_session = _SequenceSession([SimpleNamespace(rowcount=0)])
        _force_relational_session(self.client, failure_session)
        renewed = await self.client._renew_processing_lease(  # pylint: disable=protected-access
            job_id="job-rel-missing"
        )
        self.assertFalse(renewed)

    async def test_run_processing_lease_heartbeat_failure_and_loss_paths(self) -> None:
        self.client._queue_processing_lease_heartbeat_seconds = 0.001  # pylint: disable=protected-access

        renew_failure = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(
            self.client,
            "_renew_processing_lease",
            new=renew_failure,
        ):
            failure_reason = await self.client._run_processing_lease_heartbeat(  # pylint: disable=protected-access
                job_id="job-failure",
                stop_event=asyncio.Event(),
                expected_attempt=2,
            )
        self.assertEqual(failure_reason, "lease_renew_failed")
        renew_failure.assert_awaited_once_with(
            job_id="job-failure",
            expected_attempt=2,
        )

        renew_lost = AsyncMock(return_value=False)
        with patch.object(
            self.client,
            "_renew_processing_lease",
            new=renew_lost,
        ):
            loss_reason = await self.client._run_processing_lease_heartbeat(  # pylint: disable=protected-access
                job_id="job-loss",
                stop_event=asyncio.Event(),
                expected_attempt=9,
            )
        self.assertEqual(loss_reason, "lease_lost")
        renew_lost.assert_awaited_once_with(
            job_id="job-loss",
            expected_attempt=9,
        )

    async def test_processing_owner_matches_keyval_uses_processing_and_attempts(self) -> None:
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
                {
                    "version": 1,
                    "jobs": [
                        {"id": "job-1", "status": "processing", "attempts": 3},
                        {"id": "job-2", "status": "pending", "attempts": 3},
                    ],
                }
            )

        self.assertTrue(
            await self.client._processing_owner_matches(  # pylint: disable=protected-access
                job_id="job-1",
                expected_attempt=3,
            )
        )
        self.assertFalse(
            await self.client._processing_owner_matches(  # pylint: disable=protected-access
                job_id="job-1",
                expected_attempt=2,
            )
        )
        self.assertFalse(
            await self.client._processing_owner_matches(  # pylint: disable=protected-access
                job_id="job-2",
                expected_attempt=3,
            )
        )
        self.assertFalse(
            await self.client._processing_owner_matches(  # pylint: disable=protected-access
                job_id="missing-job",
                expected_attempt=3,
            )
        )

    async def test_processing_owner_matches_relational_uses_processing_and_attempts(self) -> None:
        relational_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "status": "processing",
                            "attempts": 5,
                        }
                    ]
                ),
                _SequenceResult(
                    rows=[
                        {
                            "status": "processing",
                            "attempts": 6,
                        }
                    ]
                ),
                _SequenceResult(
                    rows=[
                        {
                            "status": "pending",
                            "attempts": 6,
                        }
                    ]
                ),
                _SequenceResult(rows=[]),
            ]
        )
        _force_relational_session(self.client, relational_session)
        self.assertTrue(
            await self.client._processing_owner_matches(  # pylint: disable=protected-access
                job_id="job-rel",
                expected_attempt=5,
            )
        )
        self.assertFalse(
            await self.client._processing_owner_matches(  # pylint: disable=protected-access
                job_id="job-rel",
                expected_attempt=5,
            )
        )
        self.assertFalse(
            await self.client._processing_owner_matches(  # pylint: disable=protected-access
                job_id="job-rel",
                expected_attempt=6,
            )
        )
        self.assertFalse(
            await self.client._processing_owner_matches(  # pylint: disable=protected-access
                job_id="job-rel",
                expected_attempt=6,
            )
        )

    async def test_process_claimed_job_handles_cancelled_heartbeat_task(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-cancelled-heartbeat",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        heartbeat_task = _HeartbeatTaskDouble(
            done_sequence=[True],
            result_value=asyncio.CancelledError(),
            await_cancelled=True,
        )
        def _fake_create_task(coro, *args, **kwargs):  # noqa: ARG001
            coro.close()
            return heartbeat_task

        with (
            patch(
                "mugen.core.client.web.asyncio.create_task",
                side_effect=_fake_create_task,
            ),
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            ),
            patch.object(
                self.client,
                "_mark_job_done",
                new=AsyncMock(),
            ) as mark_done,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_done.assert_awaited_once()

    async def test_process_claimed_job_treats_heartbeat_result_errors_as_lease_failure(
        self,
    ) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-heartbeat-result-error",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        heartbeat_task = _HeartbeatTaskDouble(
            done_sequence=[True],
            result_value=RuntimeError("broken"),
        )
        def _fake_create_task(coro, *args, **kwargs):  # noqa: ARG001
            coro.close()
            return heartbeat_task

        with (
            patch(
                "mugen.core.client.web.asyncio.create_task",
                side_effect=_fake_create_task,
            ),
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            ),
            patch.object(
                self.client,
                "_mark_job_done",
                new=AsyncMock(),
            ) as mark_done,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_done.assert_not_awaited()

    async def test_process_claimed_job_skips_fallback_emit_on_lease_loss(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-skip-fallback",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        heartbeat_task = _HeartbeatTaskDouble(
            done_sequence=[False, True],
            result_value="lease_lost",
        )
        def _fake_create_task(coro, *args, **kwargs):  # noqa: ARG001
            coro.close()
            return heartbeat_task

        with (
            patch(
                "mugen.core.client.web.asyncio.create_task",
                side_effect=_fake_create_task,
            ),
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                self.client,
                "_mark_job_done",
                new=AsyncMock(),
            ) as mark_done,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_done.assert_not_awaited()
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any("stage=emit_fallback_response" in message for message in warning_messages)
        )

    async def test_process_claimed_job_skips_response_emit_on_lease_loss(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-skip-response",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        heartbeat_task = _HeartbeatTaskDouble(
            done_sequence=[False, True],
            result_value="lease_lost",
        )
        def _fake_create_task(coro, *args, **kwargs):  # noqa: ARG001
            coro.close()
            return heartbeat_task

        with (
            patch(
                "mugen.core.client.web.asyncio.create_task",
                side_effect=_fake_create_task,
            ),
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            ),
            patch.object(
                self.client,
                "_mark_job_done",
                new=AsyncMock(),
            ) as mark_done,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_done.assert_not_awaited()
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(any("stage=emit_response_0" in message for message in warning_messages))

    async def test_process_claimed_job_skips_mark_done_on_late_lease_loss(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-skip-mark-done",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        heartbeat_task = _HeartbeatTaskDouble(
            done_sequence=[False, False, True],
            result_value="lease_lost",
        )
        def _fake_create_task(coro, *args, **kwargs):  # noqa: ARG001
            coro.close()
            return heartbeat_task

        with (
            patch(
                "mugen.core.client.web.asyncio.create_task",
                side_effect=_fake_create_task,
            ),
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            ),
            patch.object(
                self.client,
                "_mark_job_done",
                new=AsyncMock(),
            ) as mark_done,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_done.assert_not_awaited()
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(any("stage=mark_done" in message for message in warning_messages))

    async def test_process_claimed_job_skips_exception_flow_on_lease_loss(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-skip-exception",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        heartbeat_task = _HeartbeatTaskDouble(
            done_sequence=[True],
            result_value="lease_lost",
        )
        def _fake_create_task(coro, *args, **kwargs):  # noqa: ARG001
            coro.close()
            return heartbeat_task

        with (
            patch(
                "mugen.core.client.web.asyncio.create_task",
                side_effect=_fake_create_task,
            ),
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch.object(
                self.client,
                "_mark_job_failed",
                new=AsyncMock(),
            ) as mark_failed,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_failed.assert_not_awaited()
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(any("stage=handle_exception" in message for message in warning_messages))

    async def test_process_claimed_job_skips_mark_failed_on_late_lease_loss(
        self,
    ) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-skip-mark-failed",
            message_type="text",
            text="hello",
        )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)
        heartbeat_task = _HeartbeatTaskDouble(
            done_sequence=[False, True],
            result_value="lease_lost",
        )
        def _fake_create_task(coro, *args, **kwargs):  # noqa: ARG001
            coro.close()
            return heartbeat_task

        with (
            patch(
                "mugen.core.client.web.asyncio.create_task",
                side_effect=_fake_create_task,
            ),
            patch.object(
                self.client,
                "_dispatch_job_to_messaging",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch.object(
                self.client,
                "_mark_job_failed",
                new=AsyncMock(),
            ) as mark_failed,
        ):
            await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        mark_failed.assert_not_awaited()
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(any("stage=mark_failed" in message for message in warning_messages))

    async def test_media_ref_collection_helper_branches(self) -> None:
        self.assertIsNone(self.client._normalise_media_ref("  "))  # pylint: disable=protected-access
        self.assertEqual(
            self.client._collect_media_refs_from_queue_payload("not-json"),  # pylint: disable=protected-access
            set(),
        )
        self.assertEqual(
            self.client._collect_media_refs_from_queue_payload(123),  # pylint: disable=protected-access
            set(),
        )
        self.assertEqual(
            self.client._collect_media_refs_from_queue_payload(  # pylint: disable=protected-access
                {"metadata": {"attachments": []}}
            ),
            set(),
        )
        self.assertEqual(
            self.client._collect_media_refs_from_queued_job("bad"),  # pylint: disable=protected-access
            set(),
        )
        self.assertEqual(
            self.client._collect_media_refs_from_composed_metadata(  # pylint: disable=protected-access
                {"attachments": "bad"}
            ),
            set(),
        )
        refs = self.client._collect_media_refs_from_composed_metadata(  # pylint: disable=protected-access
            {
                "attachments": [
                    None,
                    {"file_path": None},
                    {"file_path": " object:attachment "},
                ]
            }
        )
        self.assertEqual(refs, {"object:attachment"})

    async def test_media_token_creation_expiry_and_authorization(self) -> None:
        media_file = Path(self.tmpdir.name) / "asset.bin"
        media_file.write_bytes(b"123")

        media_payload = await self.client._create_media_token_payload(  # pylint: disable=protected-access
            file_path=str(media_file),
            owner_user_id="user-1",
            conversation_id="conv-media",
            mime_type="application/octet-stream",
            filename="asset.bin",
        )
        self.assertIsNotNone(media_payload)

        token = media_payload["token"]
        resolved = await self.client.resolve_media_download(
            auth_user="user-1",
            token=token,
        )
        self.assertIsNotNone(resolved)

        unauthorized = await self.client.resolve_media_download(
            auth_user="user-2",
            token=token,
        )
        self.assertIsNone(unauthorized)

        async with self.client._storage_lock:  # pylint: disable=protected-access
            self.relational._state.media_tokens[token]["expires_at"] = (  # pylint: disable=protected-access
                self.client._to_utc_datetime(0)  # pylint: disable=protected-access
            )

        expired = await self.client.resolve_media_download(auth_user="user-1", token=token)
        self.assertIsNone(expired)

    async def test_media_cleanup_removes_expired_tokens_and_old_files(self) -> None:
        old_ref = await self.client._media_storage_gateway.store_bytes(  # pylint: disable=protected-access
            b"x",
            filename_hint="old.bin",
        )
        active_ref = await self.client._media_storage_gateway.store_bytes(  # pylint: disable=protected-access
            b"y",
            filename_hint="active.bin",
        )
        assert isinstance(old_ref, str)
        assert isinstance(active_ref, str)

        old_file = await self.client._media_storage_gateway.materialize(old_ref)  # pylint: disable=protected-access
        active_file = await self.client._media_storage_gateway.materialize(active_ref)  # pylint: disable=protected-access
        assert isinstance(old_file, str)
        assert isinstance(active_file, str)
        os.utime(old_file, (0, 0))
        old_object_id = old_ref.split("object:", maxsplit=1)[1]
        await self.keyval.put_json(
            f"web:media:object:meta:{old_object_id}",
            {"created_at": 0.0, "extension": ".bin"},
        )

        token_payload = await self.client._create_media_token_payload(  # pylint: disable=protected-access
            file_path=active_ref,
            owner_user_id="user-1",
            conversation_id="conv-clean",
            mime_type="application/octet-stream",
            filename="active.bin",
        )

        self.relational._state.media_tokens["expired"] = {  # pylint: disable=protected-access
            "token": "expired",
            "owner_user_id": "user-1",
            "conversation_id": "conv-clean",
            "file_path": old_ref,
            "mime_type": "application/octet-stream",
            "filename": "old.bin",
            "expires_at": self.client._to_utc_datetime(0),  # pylint: disable=protected-access
        }

        self.assertIsNotNone(token_payload)
        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        self.assertNotIn("expired", self.relational._state.media_tokens)  # pylint: disable=protected-access
        self.assertFalse(Path(old_file).exists())
        self.assertTrue(Path(active_file).exists())

    async def test_media_cleanup_keeps_pending_queue_media_refs_until_terminal(self) -> None:
        queued_ref = await self.client._media_storage_gateway.store_bytes(  # pylint: disable=protected-access
            b"x",
            filename_hint="queued.bin",
        )
        assert isinstance(queued_ref, str)
        queued_file = await self.client._media_storage_gateway.materialize(queued_ref)  # pylint: disable=protected-access
        assert isinstance(queued_file, str)
        os.utime(queued_file, (0, 0))
        queued_object_id = queued_ref.split("object:", maxsplit=1)[1]
        await self.keyval.put_json(
            f"web:media:object:meta:{queued_object_id}",
            {"created_at": 0.0, "extension": ".bin"},
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
                {
                    "version": 1,
                    "jobs": [
                        {
                            "id": "job-pending-media",
                            "status": "pending",
                            "file_path": queued_ref,
                        }
                    ],
                }
            )

        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access
        self.assertTrue(Path(queued_file).exists())

        async with self.client._storage_lock:  # pylint: disable=protected-access
            queue_state = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            queue_state["jobs"][0]["status"] = "done"
            await self.client._write_queue_state_unlocked(queue_state)  # pylint: disable=protected-access

        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access
        self.assertFalse(Path(queued_file).exists())

    async def test_media_cleanup_keeps_processing_composed_attachment_refs(self) -> None:
        media_dir = Path(self.client._media_storage_path)  # pylint: disable=protected-access
        media_dir.mkdir(parents=True, exist_ok=True)
        attachment_file = media_dir / "queued-attachment.bin"
        attachment_file.write_bytes(b"x")
        os.utime(attachment_file, (0, 0))

        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
                {
                    "version": 1,
                    "jobs": [
                        {
                            "id": "job-processing-attachment",
                            "status": "processing",
                            "metadata": {
                                "attachments": [
                                    {"file_path": str(attachment_file.resolve())}
                                ]
                            },
                        }
                    ],
                }
            )

        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access
        self.assertTrue(attachment_file.exists())

    async def test_unsupported_response_type_emits_error_event(self) -> None:
        self.messaging.handle_text_message = AsyncMock(
            return_value=[{"type": "unknown", "content": "bad"}]
        )

        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-err",
            message_type="text",
            text="hello",
        )

        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        await self.client._process_claimed_job(claimed)  # pylint: disable=protected-access

        async with self.client._storage_lock:  # pylint: disable=protected-access
            events = await self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-err",
                last_event_id=None,
            )

        self.assertTrue(any(event["event"] == "error" for event in events))

    async def test_init_close_and_worker_flow_branches(self) -> None:
        await self.client.init()
        # Idempotent init path.
        await self.client.init()
        self.assertIsNotNone(self.client._worker_task)  # pylint: disable=protected-access

        # Cover worker loop branches including maintenance hook.
        loop_cfg = _build_config(basedir=self.tmpdir.name)
        loop_relational = _InMemoryWebRelationalGateway()
        loop_client = DefaultWebClient(
            config=loop_cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=loop_cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=loop_cfg,
                relational_storage_gateway=loop_relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        loop_client._queue_poll_interval_seconds = 0.001  # pylint: disable=protected-access
        counter = {"count": 0}

        async def _claim():
            counter["count"] += 1
            if counter["count"] == 1:
                return {"id": "j1", "conversation_id": "c", "sender": "u"}
            if counter["count"] >= 20:
                loop_client._worker_stop.set()  # pylint: disable=protected-access
            return None

        loop_client._claim_next_job = AsyncMock(side_effect=_claim)  # pylint: disable=protected-access
        loop_client._process_claimed_job = AsyncMock()  # pylint: disable=protected-access
        loop_client._sleep_until_poll = AsyncMock()  # pylint: disable=protected-access
        loop_client._cleanup_media_tokens_and_files = AsyncMock()  # pylint: disable=protected-access
        await loop_client._worker_loop()  # pylint: disable=protected-access

        loop_client._process_claimed_job.assert_awaited_once()  # pylint: disable=protected-access
        self.assertGreaterEqual(loop_client._sleep_until_poll.await_count, 1)  # pylint: disable=protected-access
        loop_client._cleanup_media_tokens_and_files.assert_awaited_once()  # pylint: disable=protected-access

        # Cover _sleep_until_poll timeout branch.
        sleeper_cfg = _build_config(basedir=self.tmpdir.name)
        sleeper_relational = _InMemoryWebRelationalGateway()
        sleeper = DefaultWebClient(
            config=sleeper_cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=sleeper_cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=sleeper_cfg,
                relational_storage_gateway=sleeper_relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        sleeper._queue_poll_interval_seconds = 0.001  # pylint: disable=protected-access
        await sleeper._sleep_until_poll()  # pylint: disable=protected-access
        sleeper._worker_stop.set()  # pylint: disable=protected-access
        await sleeper._sleep_until_poll()  # pylint: disable=protected-access

        await self.client.close()
        self.assertTrue(self.logger.debug.called)

    async def test_stream_events_replay_and_keepalive(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-stream",
            message_type="text",
            text="hello",
        )
        await self.client._append_event(  # pylint: disable=protected-access
            conversation_id="conv-stream",
            event_type="system",
            data={"message": "ready"},
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            stream_log = await self.client._read_event_log_unlocked("conv-stream")  # pylint: disable=protected-access
        stream_generation = str(stream_log["generation"])
        last_event_id_one = self.client._format_stream_cursor_id(  # pylint: disable=protected-access
            stream_generation=stream_generation,
            event_id=1,
        )
        last_event_id_two = self.client._format_stream_cursor_id(  # pylint: disable=protected-access
            stream_generation=stream_generation,
            event_id=2,
        )

        self.client._sse_keepalive_seconds = 0.001  # pylint: disable=protected-access
        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-stream",
            last_event_id=last_event_id_one,
        )

        first = await stream.__anext__()
        self.assertIn("event: system", first)
        keepalive = await stream.__anext__()
        self.assertEqual(keepalive, ": ping\n\n")
        # Resume once more so the `continue` after keepalive executes.
        follow_up = await stream.__anext__()
        self.assertEqual(follow_up, ": ping\n\n")
        await stream.aclose()

        # Exercise replay de-dup and live de-dup branches.
        with self.assertRaises(ValueError):
            await self.client.stream_events(
                auth_user="",
                conversation_id="conv-stream",
            )

        replay_stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-stream",
            last_event_id=last_event_id_two,
        )
        # Inject duplicate and newer live events to hit de-dup branches.
        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-stream",
            {"id": "2", "event": "system", "data": {"message": "dup"}},
        )
        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-stream",
            {"id": "9", "event": "system", "data": {"message": "new"}},
        )
        _ = await replay_stream.__anext__()
        await replay_stream.aclose()

        # Replay skip branch for event_id <= highest_event_id.
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-stream",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "stream-gen-skip",
                    "next_event_id": 3,
                    "events": [
                        {"id": "0", "event": "system", "data": {}, "created_at": "t0"},
                        {"id": "1", "event": "system", "data": {}, "created_at": "t1"},
                    ],
                },
            )
        replay_skip_stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-stream",
            last_event_id=None,
        )
        skipped_output = await replay_skip_stream.__anext__()
        self.assertIn("id: v", skipped_output)
        self.assertIn(":1", skipped_output)
        await replay_skip_stream.aclose()

        # Cover event_id None branches in replay/live paths.
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-stream",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "stream-gen-none-id",
                    "next_event_id": 2,
                    "events": [
                        {"id": "bad", "event": "system", "data": {}, "created_at": "t0"},
                    ],
                },
            )
        none_id_stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-stream",
            last_event_id=None,
        )
        first_none_id = await none_id_stream.__anext__()
        self.assertEqual(first_none_id, ": ping\n\n")
        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-stream",
            {"id": "bad-live", "event": "system", "data": {}},
        )
        second_none_id = await self._next_non_ping(none_id_stream)
        self.assertIn("id: bad-live", second_none_id)
        await none_id_stream.aclose()

        # Missing conversation branch.
        with self.assertRaises(KeyError):
            await self.client.stream_events(
                auth_user="user-1",
                conversation_id="conv-missing",
            )

    async def test_stream_events_cross_instance_poll_paths(self) -> None:
        self.client._sse_keepalive_seconds = 0.001  # pylint: disable=protected-access
        self.client._sse_cross_instance_poll_seconds = 0.001  # pylint: disable=protected-access
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-poll",
            message_type="text",
            text="seed",
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-poll",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "poll-base",
                    "next_event_id": 1,
                    "events": [],
                },
            )
        self.client._tail_events_since = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            side_effect=[
                RuntimeError("poll-failed"),
                {
                    "stream_generation": "poll-gen",
                    "events": [
                        {
                            "id": "1",
                            "event": "system",
                            "data": {"message": "polled"},
                            "created_at": None,
                            "stream_generation": "poll-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        }
                    ],
                },
                {
                    "stream_generation": "poll-gen",
                    "events": [],
                },
            ]
        )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-poll",
            last_event_id=None,
        )

        reset_chunk = await self._next_non_ping(stream)
        self.assertTrue(
            '"reason":"poll_generation_changed"' in reset_chunk
            or '"reason":"live_generation_changed"' in reset_chunk
        )
        polled_chunk = await self._next_non_ping(stream)
        if '"signal":"stream_reset"' in polled_chunk:
            polled_chunk = await self._next_non_ping(stream)
        self.assertIn(":poll-gen:1", polled_chunk)
        keepalive_chunk = await stream.__anext__()
        self.assertEqual(keepalive_chunk, ": ping\n\n")

        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-poll",
            {
                "id": "2",
                "event": "system",
                "data": {"message": "live"},
                "stream_generation": "poll-gen",
                "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            },
        )
        live_chunk = await self._next_non_ping(stream)
        self.assertIn(":poll-gen:2", live_chunk)
        await stream.aclose()

        self.assertGreater(
            self.client._web_metrics.get("web.sse.poll.cycles", 0), 0  # pylint: disable=protected-access
        )
        self.assertGreater(
            self.client._web_metrics.get("web.sse.poll.events", 0), 0  # pylint: disable=protected-access
        )
        self.assertGreater(
            self.client._web_metrics.get("web.sse.poll.errors", 0), 0  # pylint: disable=protected-access
        )

    async def test_stream_events_emits_replay_cursor_gap_reset(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-replay-gap",
            message_type="text",
            text="seed",
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-replay-gap",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "replay-gap-gen",
                    "next_event_id": 6,
                    "events": [
                        {
                            "id": "5",
                            "event": "system",
                            "data": {"message": "replay-gap"},
                            "created_at": "t0",
                            "stream_generation": "replay-gap-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        }
                    ],
                },
            )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-replay-gap",
            last_event_id=self.client._format_stream_cursor_id(  # pylint: disable=protected-access
                stream_generation="replay-gap-gen",
                event_id=1,
            ),
        )

        reset_chunk = await self._next_non_ping(stream)
        self.assertIn('"reason":"replay_cursor_gap"', reset_chunk)
        replay_chunk = await self._next_non_ping(stream)
        self.assertIn(":replay-gap-gen:5", replay_chunk)
        await stream.aclose()

    async def test_stream_events_emits_poll_cursor_gap_reset(self) -> None:
        self.client._sse_keepalive_seconds = 60.0  # pylint: disable=protected-access
        self.client._sse_cross_instance_poll_seconds = 0.001  # pylint: disable=protected-access
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-poll-gap",
            message_type="text",
            text="seed",
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-poll-gap",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "poll-gap-gen",
                    "next_event_id": 1,
                    "events": [],
                },
            )
        self.client._tail_events_since = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            side_effect=[
                {
                    "stream_generation": "poll-gap-gen",
                    "requested_after_event_id": 10,
                    "effective_after_event_id": 10,
                    "first_event_id": 15,
                    "events": [
                        {
                            "id": "15",
                            "event": "system",
                            "data": {"message": "poll-gap"},
                            "created_at": None,
                            "stream_generation": "poll-gap-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        }
                    ],
                },
                {
                    "stream_generation": "poll-gap-gen",
                    "requested_after_event_id": 15,
                    "effective_after_event_id": 15,
                    "first_event_id": None,
                    "events": [],
                },
            ]
        )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-poll-gap",
            last_event_id=None,
        )

        reset_chunk = await self._next_non_ping(stream)
        self.assertIn('"reason":"poll_cursor_gap"', reset_chunk)
        polled_chunk = await self._next_non_ping(stream)
        self.assertIn(":poll-gap-gen:15", polled_chunk)
        await stream.aclose()

    async def test_stream_events_does_not_emit_reset_when_replay_cursor_is_contiguous(
        self,
    ) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-replay-no-gap",
            message_type="text",
            text="seed",
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-replay-no-gap",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "replay-nogap-gen",
                    "next_event_id": 3,
                    "events": [
                        {
                            "id": "2",
                            "event": "system",
                            "data": {"message": "replay-no-gap"},
                            "created_at": "t0",
                            "stream_generation": "replay-nogap-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        }
                    ],
                },
            )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-replay-no-gap",
            last_event_id=self.client._format_stream_cursor_id(  # pylint: disable=protected-access
                stream_generation="replay-nogap-gen",
                event_id=1,
            ),
        )

        replay_chunk = await self._next_non_ping(stream)
        self.assertNotIn('"signal":"stream_reset"', replay_chunk)
        self.assertIn(":replay-nogap-gen:2", replay_chunk)
        await stream.aclose()

    async def test_stream_events_poll_stable_generation_and_live_event_paths(self) -> None:
        self.client._sse_keepalive_seconds = 60.0  # pylint: disable=protected-access
        self.client._sse_cross_instance_poll_seconds = 0.001  # pylint: disable=protected-access
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-poll-stable",
            message_type="text",
            text="seed",
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-poll-stable",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "stable-gen",
                    "next_event_id": 1,
                    "events": [],
                },
            )
        self.client._tail_events_since = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            side_effect=[
                {
                    "stream_generation": "stable-gen",
                    "events": [
                        {
                            "id": "bad-id",
                            "event": "system",
                            "data": {"message": "non-numeric"},
                            "created_at": None,
                            "stream_generation": "stable-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        }
                    ],
                },
                {
                    "stream_generation": "stable-gen",
                    "events": [
                        {
                            "id": "1",
                            "event": "system",
                            "data": {"message": "numeric"},
                            "created_at": None,
                            "stream_generation": "stable-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        }
                    ],
                },
            ]
        )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-poll-stable",
            last_event_id=None,
        )

        first_polled = await stream.__anext__()
        self.assertIn("id: bad-id", first_polled)
        second_polled = await stream.__anext__()
        self.assertIn(":stable-gen:1", second_polled)

        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-poll-stable",
            {
                "id": "2",
                "event": "system",
                "data": {"message": "live"},
                "stream_generation": "stable-gen",
                "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            },
        )
        live_chunk = await self._next_non_ping(stream)
        self.assertIn(":stable-gen:2", live_chunk)

        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-poll-stable",
            {
                "id": "3",
                "event": "system",
                "data": {"message": "live-2"},
                "stream_generation": "stable-gen",
                "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            },
        )
        second_live_chunk = await self._next_non_ping(stream)
        self.assertIn(":stable-gen:3", second_live_chunk)
        await stream.aclose()

    async def test_stream_events_poll_skips_duplicate_ids_by_cursor(self) -> None:
        self.client._sse_keepalive_seconds = 60.0  # pylint: disable=protected-access
        self.client._sse_cross_instance_poll_seconds = 0.001  # pylint: disable=protected-access
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-poll-duplicate",
            message_type="text",
            text="seed",
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-poll-duplicate",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "dup-gen",
                    "next_event_id": 1,
                    "events": [],
                },
            )
        self.client._tail_events_since = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            side_effect=[
                {
                    "stream_generation": "dup-gen",
                    "events": [
                        {
                            "id": "1",
                            "event": "system",
                            "data": {"message": "first"},
                            "created_at": None,
                            "stream_generation": "dup-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        }
                    ],
                },
                {
                    "stream_generation": "dup-gen",
                    "events": [
                        {
                            "id": "1",
                            "event": "system",
                            "data": {"message": "duplicate"},
                            "created_at": None,
                            "stream_generation": "dup-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        },
                        {
                            "id": "2",
                            "event": "system",
                            "data": {"message": "second"},
                            "created_at": None,
                            "stream_generation": "dup-gen",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        },
                    ],
                },
            ]
        )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-poll-duplicate",
            last_event_id=None,
        )
        first_chunk = await self._next_non_ping(stream)
        self.assertIn(":dup-gen:1", first_chunk)
        second_chunk = await self._next_non_ping(stream)
        self.assertIn(":dup-gen:2", second_chunk)
        self.assertNotIn("duplicate", second_chunk)
        await stream.aclose()

    async def test_stream_events_share_single_cross_instance_poller_per_conversation(
        self,
    ) -> None:
        self.client._sse_keepalive_seconds = 60.0  # pylint: disable=protected-access
        self.client._sse_cross_instance_poll_seconds = 0.001  # pylint: disable=protected-access
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-shared-poller",
            message_type="text",
            text="seed",
        )
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-shared-poller",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "shared-gen",
                    "next_event_id": 1,
                    "events": [],
                },
            )

        self.client._tail_events_since = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={
                "stream_generation": "shared-gen",
                "events": [],
            }
        )

        stream_a = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-shared-poller",
        )
        stream_b = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-shared-poller",
        )

        next_a = asyncio.create_task(stream_a.__anext__())
        next_b = asyncio.create_task(stream_b.__anext__())
        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-shared-poller",
            {
                "id": "1",
                "event": "system",
                "data": {"message": "fanout"},
                "stream_generation": "shared-gen",
                "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            },
        )
        await asyncio.wait_for(next_a, timeout=1.0)
        await asyncio.wait_for(next_b, timeout=1.0)

        self.assertEqual(
            len(self.client._sse_cross_instance_pollers),  # pylint: disable=protected-access
            1,
        )
        await asyncio.sleep(0.01)
        self.assertGreater(self.client._tail_events_since.await_count, 0)  # pylint: disable=protected-access

        await stream_a.aclose()
        await stream_b.aclose()
        await asyncio.sleep(0)
        self.assertEqual(
            len(self.client._sse_cross_instance_pollers),  # pylint: disable=protected-access
            0,
        )

    async def test_stream_events_resets_stale_cursor_and_emits_low_live_ids(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-reset",
            message_type="text",
            text="hello",
            client_message_id="cid-reset",
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-reset",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "restart-gen",
                    "next_event_id": 1,
                    "events": [],
                },
            )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-reset",
            last_event_id="999",
        )

        reset_chunk = await stream.__anext__()
        self.assertIn("event: system", reset_chunk)
        reset_data_lines = [
            line[6:] for line in reset_chunk.splitlines() if line.startswith("data: ")
        ]
        reset_payload = json.loads("\n".join(reset_data_lines))
        self.assertEqual(reset_payload["signal"], "stream_reset")
        self.assertEqual(reset_payload["reason"], "invalid_last_event_id")

        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-reset",
            {
                "id": "1",
                "event": "system",
                "data": {
                    "conversation_id": "conv-reset",
                    "job_id": "job-1",
                    "client_message_id": "cid-reset",
                    "message": "after restart",
                },
                "stream_generation": "restart-gen",
                "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            },
        )
        live_chunk = await stream.__anext__()
        self.assertIn(
            f"id: v{self.client._event_log_version}:restart-gen:1",  # pylint: disable=protected-access
            live_chunk,
        )
        await stream.aclose()

    async def test_append_event_adds_missing_correlation_keys(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-corr",
            message_type="text",
            text="hello",
            client_message_id="cid-corr",
        )

        await self.client._append_event(  # pylint: disable=protected-access
            conversation_id="conv-corr",
            event_type="system",
            data={"conversation_id": "conv-corr", "message": "state"},
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            events = await self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-corr",
                last_event_id=None,
            )

        state_event = next(
            event
            for event in events
            if event["event"] == "system" and event["data"].get("message") == "state"
        )
        self.assertIn("job_id", state_event["data"])
        self.assertIn("client_message_id", state_event["data"])
        self.assertIsNone(state_event["data"]["job_id"])
        self.assertIsNone(state_event["data"]["client_message_id"])

        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "Web event correlation keys missing; defaulted to null" in message
                and "event_type=system" in message
                for message in warning_messages
            )
        )

    async def test_publish_event_logs_dropped_event_diagnostics(self) -> None:
        class _AlwaysBackpressuredQueue:
            def __init__(self) -> None:
                self._drained = False

            async def put(self, _item):
                await asyncio.sleep(1)

            def put_nowait(self, _item):
                if self._drained:
                    return
                raise asyncio.QueueFull()

            def get_nowait(self):
                if self._drained:
                    raise asyncio.QueueEmpty()
                self._drained = True
                return {"id": "1"}

        async with self.client._subscriber_lock:  # pylint: disable=protected-access
            self.client._subscribers["conv-drop"] = {  # pylint: disable=protected-access
                _AlwaysBackpressuredQueue()
            }

        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-drop",
            {"id": "2", "event": "system", "data": {}},
        )

        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "Web SSE event skipped/dropped" in message
                and "conversation_id='conv-drop'" in message
                and "incoming_event_id='2'" in message
                and "reason='subscriber_enqueue_timeout_disconnect'" in message
                for message in warning_messages
            )
        )

    async def test_publish_event_logs_fanout_delivery_exception(self) -> None:
        class _QueueRaising:
            async def put(self, _item):
                raise RuntimeError("fanout boom")

        async with self.client._subscriber_lock:  # pylint: disable=protected-access
            self.client._subscribers["conv-fanout-error"] = {  # pylint: disable=protected-access
                _QueueRaising()
            }

        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-fanout-error",
            {"id": "2", "event": "system", "data": {}},
        )

        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "Web SSE fan-out delivery failed" in message
                and "RuntimeError" in message
                and "fanout boom" in message
                for message in warning_messages
            )
        )

    async def test_sse_fanout_dispatcher_handles_result_level_exceptions(self) -> None:
        class _QueueRaising:
            async def put(self, _item):
                raise RuntimeError("fanout boom")

        dispatcher = web_mod._SSEFanoutDispatcher(  # pylint: disable=protected-access
            enqueue_timeout_seconds=0.01,
            parallelism=1,
        )
        on_error_calls: list[str] = []

        def _on_error(exc: Exception) -> None:
            on_error_calls.append(type(exc).__name__)
            if len(on_error_calls) == 1:
                raise ValueError("handler-failed")

        summary = await dispatcher.publish(
            subscribers=[_QueueRaising()],
            event_entry={"id": "1"},
            on_timeout=AsyncMock(),
            on_error=_on_error,
        )

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(on_error_calls, ["RuntimeError", "ValueError"])

    async def test_stream_events_handles_non_positive_next_event_id(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-next-zero",
            message_type="text",
            text="hello",
            client_message_id="cid-next-zero",
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-next-zero",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "gen-zero",
                    "next_event_id": 0,
                    "events": [],
                },
            )

        self.client._sse_keepalive_seconds = 0.001  # pylint: disable=protected-access
        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-next-zero",
            last_event_id=None,
        )
        self.assertEqual(await stream.__anext__(), ": ping\n\n")
        await stream.aclose()

    async def test_stream_events_replay_and_live_generation_change_paths(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-gen-change",
            message_type="text",
            text="hello",
            client_message_id="cid-gen-change",
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
                "conv-gen-change",
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "gen-a",
                    "next_event_id": 3,
                    "events": [
                        {
                            "id": "2",
                            "event": "system",
                            "data": {
                                "conversation_id": "conv-gen-change",
                                "job_id": "job-1",
                                "client_message_id": "cid-gen-change",
                                "message": "first",
                            },
                            "created_at": "t1",
                            "stream_generation": "gen-b",
                        },
                        {
                            "id": "2",
                            "event": "system",
                            "data": {
                                "conversation_id": "conv-gen-change",
                                "job_id": "job-1",
                                "client_message_id": "cid-gen-change",
                                "message": "duplicate",
                            },
                            "created_at": "t2",
                            "stream_generation": "gen-b",
                        },
                    ],
                },
            )

        self.client._sse_keepalive_seconds = 0.001  # pylint: disable=protected-access
        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-gen-change",
            last_event_id=None,
        )

        replay_reset_chunk = await stream.__anext__()
        self.assertIn('"reason":"replay_generation_changed"', replay_reset_chunk)
        replay_event_chunk = await stream.__anext__()
        self.assertIn(":gen-b:2", replay_event_chunk)

        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-gen-change",
            {
                "id": "1",
                "event": "system",
                "data": {
                    "conversation_id": "conv-gen-change",
                    "job_id": "job-2",
                    "client_message_id": "cid-gen-change",
                    "message": "live",
                },
                "stream_generation": "gen-c",
                "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            },
        )
        live_reset_chunk = await self._next_non_ping(stream)
        self.assertIn('"reason":"live_generation_changed"', live_reset_chunk)
        live_event_chunk = await self._next_non_ping(stream)
        self.assertIn(":gen-c:1", live_event_chunk)
        await stream.aclose()

        debug_messages = [call.args[0] for call in self.logger.debug.call_args_list]
        self.assertTrue(
            any(
                "reason='replay_generation_changed'" in message
                for message in debug_messages
            )
        )

    async def test_stream_events_replay_dedup_and_live_control_payload_branches(self) -> None:
        self.client._ensure_conversation_owner_unlocked = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        self.client._read_event_log_unlocked = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={
                "version": self.client._event_log_version,  # pylint: disable=protected-access
                "generation": "gen-dup",
                "next_event_id": 3,
                "events": [
                    {"id": "2", "event": "system", "data": {}, "stream_generation": "gen-dup"},
                    {"id": "1", "event": "system", "data": {}, "stream_generation": "gen-dup"},
                ],
            }
        )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-dup",
            last_event_id=None,
        )
        replay_chunk = await stream.__anext__()
        self.assertIn(":gen-dup:2", replay_chunk)

        async with self.client._subscriber_lock:  # pylint: disable=protected-access
            subscriber = next(iter(self.client._subscribers["conv-dup"]))  # pylint: disable=protected-access
        await subscriber.put("invalid-live-event")
        await subscriber.put(self.client._sse_disconnect_sentinel)  # pylint: disable=protected-access

        with self.assertRaises(StopAsyncIteration):
            await stream.__anext__()

        debug_messages = [call.args[0] for call in self.logger.debug.call_args_list]
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "reason='replay_event_id_not_greater_than_cursor'" in message
                for message in debug_messages
            )
        )
        self.assertTrue(
            any("reason='live_event_invalid_payload'" in message for message in debug_messages)
        )
        self.assertTrue(
            any(
                "reason='subscriber_disconnected_for_backpressure'" in message
                for message in warning_messages
            )
        )

    async def test_stream_events_replay_allows_non_numeric_event_id(self) -> None:
        self.client._ensure_conversation_owner_unlocked = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        self.client._read_event_log_unlocked = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={
                "version": self.client._event_log_version,  # pylint: disable=protected-access
                "generation": "gen-none-id",
                "next_event_id": 2,
                "events": [
                    {"id": "bad", "event": "system", "data": {}, "stream_generation": "gen-none-id"},
                ],
            }
        )

        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-none-id",
            last_event_id=None,
        )
        replay_chunk = await stream.__anext__()
        self.assertIn("id: bad", replay_chunk)
        await stream.aclose()

    def test_first_numeric_event_id_helper_handles_non_list_and_non_dict_items(self) -> None:
        self.assertIsNone(self.client._first_numeric_event_id(None))  # pylint: disable=protected-access
        self.assertEqual(
            self.client._first_numeric_event_id(["bad", {"id": "3"}]),  # pylint: disable=protected-access
            3,
        )

    async def test_disconnect_subscriber_for_backpressure_helper_branches(self) -> None:
        queue = asyncio.Queue(maxsize=1)
        await self.client._register_subscriber("conv-disconnect", queue)  # pylint: disable=protected-access
        await self.client._disconnect_subscriber_for_backpressure(  # pylint: disable=protected-access
            conversation_id="conv-disconnect",
            subscriber=queue,
        )
        self.assertIs(queue.get_nowait(), self.client._sse_disconnect_sentinel)  # pylint: disable=protected-access

        class _QueueAlwaysFull:
            def __init__(self) -> None:
                self._drained = False

            def put_nowait(self, _item):
                raise asyncio.QueueFull()

            def get_nowait(self):
                if self._drained:
                    raise asyncio.QueueEmpty()
                self._drained = True
                return {"id": "x"}

        subscriber = _QueueAlwaysFull()
        async with self.client._subscriber_lock:  # pylint: disable=protected-access
            self.client._subscribers["conv-disconnect-warn"] = {subscriber}  # pylint: disable=protected-access
        await self.client._disconnect_subscriber_for_backpressure(  # pylint: disable=protected-access
            conversation_id="conv-disconnect-warn",
            subscriber=subscriber,
        )
        self.assertTrue(
            any(
                "Failed to enqueue SSE disconnect sentinel" in call.args[0]
                for call in self.logger.warning.call_args_list
            )
        )

    def test_collect_media_refs_from_queued_job_and_metadata_branches(self) -> None:
        refs = self.client._collect_media_refs_from_queued_job(  # pylint: disable=protected-access
            {"file_path": " /tmp/file.bin ", "metadata": None}
        )
        self.assertEqual(refs, {"/tmp/file.bin"})
        refs_without_file = self.client._collect_media_refs_from_queued_job(  # pylint: disable=protected-access
            {
                "file_path": None,
                "metadata": {"attachments": [{"file_path": " object:blob "}]},
            }
        )
        self.assertEqual(refs_without_file, {"object:blob"})
        self.assertEqual(
            self.client._collect_media_refs_from_composed_metadata(None),  # pylint: disable=protected-access
            set(),
        )

    async def test_stream_cursor_and_correlation_helper_branches(self) -> None:
        self.relational._state.conversation_states["conv-helper"] = {  # pylint: disable=protected-access
            "conversation_id": "conv-helper",
            "owner_user_id": "user-1",
            "stream_generation": "gen-helper",
            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            "next_event_id": "bad",
        }
        malformed_events = await self.client._read_event_log_unlocked("conv-helper")  # pylint: disable=protected-access
        self.assertEqual(malformed_events["events"], [])
        self.assertEqual(malformed_events["next_event_id"], 1)

        self.relational._state.conversation_states["conv-helper"]["next_event_id"] = -9  # pylint: disable=protected-access
        non_positive_next = await self.client._read_event_log_unlocked("conv-helper")  # pylint: disable=protected-access
        self.assertEqual(non_positive_next["next_event_id"], 1)

        fallback_client_message_id = self.client._normalize_client_message_id(  # pylint: disable=protected-access
            client_message_id=" ",
            job_id="job-x",
            conversation_id="conv-helper",
            source="test",
            event_type="ack",
        )
        self.assertEqual(fallback_client_message_id, "auto-job-x")

        with self.assertRaises(ValueError):
            self.client._normalize_event_payload_with_correlation(  # pylint: disable=protected-access
                conversation_id="conv-helper",
                event_type="system",
                data=[],  # type: ignore[arg-type]
            )

        passthrough = self.client._normalize_event_payload_with_correlation(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            event_type="custom",
            data={"x": 1},
        )
        self.assertEqual(passthrough, {"x": 1})

        normalized = self.client._normalize_event_payload_with_correlation(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            event_type="system",
            data={"job_id": " ", "client_message_id": 123},
        )
        self.assertIsNone(normalized["job_id"])
        self.assertEqual(normalized["client_message_id"], "123")

        no_id_stream_event = self.client._build_stream_sse_event(  # pylint: disable=protected-access
            event={"event": "system", "data": "payload"},
            stream_generation="gen-helper",
        )
        self.assertEqual(no_id_stream_event["id"], "")
        self.assertEqual(no_id_stream_event["data"]["payload"], "payload")

        invalid_cursor = self.client._resolve_stream_cursor(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            incoming_last_event_id="bad-cursor",
            stream_generation="gen-helper",
        )
        self.assertIsNotNone(invalid_cursor["reset_event"])

        version_mismatch_cursor = self.client._resolve_stream_cursor(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            incoming_last_event_id="v999:gen-helper:1",
            stream_generation="gen-helper",
        )
        self.assertIsNotNone(version_mismatch_cursor["reset_event"])

        generation_mismatch_cursor = self.client._resolve_stream_cursor(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            incoming_last_event_id=(
                f"v{self.client._event_log_version}:other-generation:1"  # pylint: disable=protected-access
            ),
            stream_generation="gen-helper",
        )
        self.assertIsNotNone(generation_mismatch_cursor["reset_event"])

        matching_cursor = self.client._resolve_stream_cursor(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            incoming_last_event_id=(
                f"v{self.client._event_log_version}:gen-helper:1"  # pylint: disable=protected-access
            ),
            stream_generation="gen-helper",
        )
        self.assertIsNone(matching_cursor["reset_event"])
        self.assertEqual(matching_cursor["effective_last_event_id"], 1)

        parsed_empty = self.client._parse_stream_cursor(" ")  # pylint: disable=protected-access
        self.assertFalse(parsed_empty["invalid"])

        parsed_bad_version = self.client._parse_stream_cursor("vx:gen:1")  # pylint: disable=protected-access
        self.assertTrue(parsed_bad_version["invalid"])

        parsed_bad_triplet = self.client._parse_stream_cursor("v0:gen:x")  # pylint: disable=protected-access
        self.assertTrue(parsed_bad_triplet["invalid"])

        parsed_valid = self.client._parse_stream_cursor(  # pylint: disable=protected-access
            f"v{self.client._event_log_version}:gen:7"  # pylint: disable=protected-access
        )
        self.assertEqual(parsed_valid["event_id"], 7)
        self.assertFalse(parsed_valid["invalid"])

        parsed_invalid_legacy = self.client._parse_stream_cursor("legacy:bad")  # pylint: disable=protected-access
        self.assertTrue(parsed_invalid_legacy["invalid"])

        self.assertEqual(
            self.client._normalize_stream_generation("", fallback="fallback"),  # pylint: disable=protected-access
            "fallback",
        )

    async def test_resolve_media_download_invalid_branches(self) -> None:
        self.assertIsNone(
            await self.client.resolve_media_download(auth_user="user-1", token="unknown")
        )

        self.relational._state.media_tokens["bad-token"] = {  # pylint: disable=protected-access
            "token": "bad-token",
            "owner_user_id": "user-1",
            "conversation_id": "conv-invalid",
            "file_path": os.path.join(self.tmpdir.name, "missing.bin"),
            "mime_type": "application/octet-stream",
            "filename": "missing.bin",
            "expires_at": self.client._to_utc_datetime(0),  # pylint: disable=protected-access
        }
        self.assertIsNone(
            await self.client.resolve_media_download(auth_user="user-1", token="bad-token")
        )

        self.relational._state.media_tokens["owner-mismatch"] = {  # pylint: disable=protected-access
            "token": "owner-mismatch",
            "owner_user_id": "other",
            "conversation_id": "conv-invalid",
            "file_path": "x",
            "mime_type": "application/octet-stream",
            "filename": "x.bin",
            "expires_at": self.client._to_utc_datetime(9999999999),  # pylint: disable=protected-access
        }
        self.assertIsNone(
            await self.client.resolve_media_download(
                auth_user="user-1", token="owner-mismatch"
            )
        )

        self.relational._state.media_tokens["empty-path"] = {  # pylint: disable=protected-access
            "token": "empty-path",
            "owner_user_id": "user-1",
            "conversation_id": "conv-invalid",
            "file_path": "",
            "mime_type": "application/octet-stream",
            "filename": "x.bin",
            "expires_at": self.client._to_utc_datetime(9999999999),  # pylint: disable=protected-access
        }
        self.assertIsNone(
            await self.client.resolve_media_download(auth_user="user-1", token="empty-path")
        )

        self.relational._state.media_tokens["missing-file"] = {  # pylint: disable=protected-access
            "token": "missing-file",
            "owner_user_id": "user-1",
            "conversation_id": "conv-invalid",
            "file_path": os.path.join(self.tmpdir.name, "missing.bin"),
            "mime_type": "application/octet-stream",
            "filename": "missing.bin",
            "expires_at": self.client._to_utc_datetime(9999999999),  # pylint: disable=protected-access
        }
        self.assertIsNone(
            await self.client.resolve_media_download(auth_user="user-1", token="missing-file")
        )

    async def test_dispatch_and_response_branches(self) -> None:
        media_file_path = os.path.join(self.tmpdir.name, "dispatch-media.bin")
        with open(media_file_path, "wb") as handle:
            handle.write(b"payload")
        media_ref = await self.client._persist_media_reference(  # pylint: disable=protected-access
            file_path=media_file_path,
            filename_hint="dispatch-media.bin",
        )
        self.assertIsNotNone(media_ref)
        job = {
            "conversation_id": "conv-d",
            "sender": "user-1",
            "metadata": {},
            "client_message_id": "cid",
            "file_path": media_ref,
            "mime_type": "image/png",
            "original_filename": "name.png",
        }

        self.messaging.handle_audio_message = AsyncMock(return_value=[])
        self.messaging.handle_video_message = AsyncMock(return_value=[])
        self.messaging.handle_image_message = AsyncMock(return_value=[])
        await self.client._dispatch_job_to_messaging({**job, "message_type": "audio"})  # pylint: disable=protected-access
        await self.client._dispatch_job_to_messaging({**job, "message_type": "video"})  # pylint: disable=protected-access
        await self.client._dispatch_job_to_messaging({**job, "message_type": "image"})  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            await self.client._dispatch_job_to_messaging(  # pylint: disable=protected-access
                {**job, "message_type": "audio", "file_path": "missing-file"}
            )

        with self.assertRaises(ValueError):
            await self.client._dispatch_job_to_messaging(  # pylint: disable=protected-access
                {**job, "message_type": "unknown"}
            )

        non_dict = await self.client._response_to_event(  # pylint: disable=protected-access
            response=123,
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(non_dict["event_type"], "message")

        missing_type = await self.client._response_to_event(  # pylint: disable=protected-access
            response={},
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(missing_type["event_type"], "error")

        text_event = await self.client._response_to_event(  # pylint: disable=protected-access
            response={"type": "text", "content": None},
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(text_event["event_type"], "message")
        self.assertEqual(
            text_event["payload"]["message"]["content"],
            "No response generated.",
        )

        # media dict URL passthrough path
        media_event = await self.client._response_to_event(  # pylint: disable=protected-access
            response={"type": "image", "content": {"url": "https://x"}},
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(media_event["event_type"], "message")

        audio_file = Path(self.tmpdir.name) / "audio.ogg"
        audio_file.write_bytes(b"ogg")
        audio_event = await self.client._response_to_event(  # pylint: disable=protected-access
            response={
                "type": "audio",
                "file": {
                    "uri": str(audio_file),
                    "type": "audio/ogg",
                    "name": "audio.ogg",
                },
            },
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(audio_event["event_type"], "message")
        self.assertEqual(audio_event["payload"]["message"]["type"], "audio")
        self.assertEqual(
            audio_event["payload"]["message"]["content"]["mime_type"],
            "audio/ogg",
        )
        audio_token = audio_event["payload"]["message"]["content"]["token"]
        resolved_audio = await self.client.resolve_media_download(
            auth_user="user-1",
            token=audio_token,
        )
        self.assertIsNotNone(resolved_audio)
        self.assertNotEqual(
            resolved_audio["file_path"],
            os.path.abspath(str(audio_file)),
        )
        self.assertTrue(os.path.exists(resolved_audio["file_path"]))

        nested_audio_event = await self.client._response_to_event(  # pylint: disable=protected-access
            response={
                "type": "audio",
                "content": {
                    "file": {
                        "uri": str(audio_file),
                        "type": "audio/ogg",
                        "name": "nested.ogg",
                    }
                },
            },
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(nested_audio_event["event_type"], "message")

        buffer_audio_event = await self.client._response_to_event(  # pylint: disable=protected-access
            response={
                "type": "audio",
                "file": {
                    "uri": io.BytesIO(b"buffer-audio-bytes"),
                    "type": "audio/mpeg",
                    "name": "buffer-audio.mp3",
                },
            },
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(buffer_audio_event["event_type"], "message")
        buffer_token = buffer_audio_event["payload"]["message"]["content"]["token"]
        resolved_buffer_audio = await self.client.resolve_media_download(
            auth_user="user-1",
            token=buffer_token,
        )
        self.assertIsNotNone(resolved_buffer_audio)
        self.assertEqual(resolved_buffer_audio["mime_type"], "audio/mpeg")
        self.assertTrue(os.path.exists(resolved_buffer_audio["file_path"]))
        with open(resolved_buffer_audio["file_path"], "rb") as handle:
            self.assertEqual(handle.read(), b"buffer-audio-bytes")

        bad_media = await self.client._response_to_event(  # pylint: disable=protected-access
            response={"type": "image", "content": {"file_path": "missing"}},
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(bad_media["event_type"], "error")

        composed_response = await self.client._response_to_event(  # pylint: disable=protected-access
            response={"type": "composed", "content": {"x": 1}},
            sender="user-1",
            conversation_id="conv-d",
        )
        self.assertEqual(composed_response["event_type"], "error")

        self.assertFalse(self.client._is_blank_text_response(123))  # pylint: disable=protected-access

        self.assertIsNone(
            await self.client._build_media_payload(  # pylint: disable=protected-access
                content=None,
                owner_user_id="user-1",
                conversation_id="conv-d",
            )
        )

        existing = Path(self.tmpdir.name) / "media.bin"
        existing.write_bytes(b"x")
        payload = await self.client._build_media_payload(  # pylint: disable=protected-access
            content=str(existing),
            owner_user_id="user-1",
            conversation_id="conv-d",
            fallback_mime_type="application/octet-stream",
            fallback_filename="media.bin",
        )
        self.assertIsNotNone(payload)

        self.assertIsNone(
            await self.client._create_media_token_payload(  # pylint: disable=protected-access
                file_path=None,
                owner_user_id="user-1",
                conversation_id="conv-d",
                mime_type=None,
                filename=None,
            )
        )
        self.assertIsNone(
            await self.client._create_media_token_payload(  # pylint: disable=protected-access
                file_path=os.path.join(self.tmpdir.name, "missing.bin"),
                owner_user_id="user-1",
                conversation_id="conv-d",
                mime_type=None,
                filename=None,
            )
        )

        # process_claimed_job exception branch.
        failing_cfg = _build_config(basedir=self.tmpdir.name)
        failing_relational = _InMemoryWebRelationalGateway()
        failing = DefaultWebClient(
            config=failing_cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=failing_cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=failing_cfg,
                relational_storage_gateway=failing_relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        await failing.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-f",
            message_type="text",
            text="hello",
        )
        claimed = await failing._claim_next_job()  # pylint: disable=protected-access
        failing._dispatch_job_to_messaging = AsyncMock(side_effect=RuntimeError("boom"))  # pylint: disable=protected-access
        await failing._process_claimed_job(claimed)  # pylint: disable=protected-access

        async with failing._storage_lock:  # pylint: disable=protected-access
            failure_events = await failing._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-f",
                last_event_id=None,
            )

        self.assertEqual(failure_events[1]["event"], "thinking")
        self.assertEqual(failure_events[1]["data"]["state"], "start")
        self.assertEqual(failure_events[2]["event"], "error")
        self.assertEqual(failure_events[3]["event"], "thinking")
        self.assertEqual(failure_events[3]["data"]["state"], "stop")
        await failing.close()

    async def test_dispatch_composed_paths(self) -> None:
        composed_text_job = {
            "conversation_id": "conv-composed-text",
            "sender": "user-1",
            "client_message_id": "cid-composed-text",
            "message_type": "composed",
            "metadata": {
                "composition_mode": "message_with_attachments",
                "parts": [
                    {"type": "text", "text": "first"},
                    {"type": "attachment", "id": "a1", "caption": "cap-1"},
                    {"type": "text", "text": "second"},
                ],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1.bin",
                        "mime_type": "application/octet-stream",
                        "original_filename": "a1.bin",
                        "metadata": {"k": "v"},
                        "caption": "cap-1",
                    }
                ],
            },
        }

        self.messaging.handle_composed_message = AsyncMock(
            return_value=[{"type": "text", "content": "composed"}]
        )
        text_responses = await self.client._dispatch_job_to_messaging(  # pylint: disable=protected-access
            composed_text_job
        )
        self.assertEqual(text_responses, [{"type": "text", "content": "composed"}])
        self.messaging.handle_composed_message.assert_awaited_once()
        composed_kwargs = self.messaging.handle_composed_message.await_args.kwargs
        self.assertEqual(composed_kwargs["platform"], "web")
        self.assertEqual(composed_kwargs["room_id"], "conv-composed-text")
        self.assertEqual(composed_kwargs["sender"], "user-1")
        self.assertEqual(composed_kwargs["message"]["client_message_id"], "cid-composed-text")
        self.assertEqual(composed_kwargs["message"]["parts"][1]["id"], "a1")
        self.assertEqual(composed_kwargs["message"]["parts"][1]["caption"], "cap-1")

        with self.assertRaises(ValueError):
            await self.client._dispatch_job_to_messaging(  # pylint: disable=protected-access
                {
                    **composed_text_job,
                    "metadata": {
                        "composition_mode": "message_with_attachments",
                        "parts": [],
                        "attachments": [],
                    },
                }
            )

    async def test_composed_metadata_helper_branches(self) -> None:
        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(None)  # pylint: disable=protected-access

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "bad",
                    "parts": [],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": {},
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": [1],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": [
                        {"id": "a1", "file_path": "/tmp/a1.bin"},
                        {"id": "a1", "file_path": "/tmp/a2.bin"},
                    ],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": [{"id": "a1", "file_path": "/tmp/x", "metadata": []}],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": {},
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [1],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [{"type": "attachment", "id": "a1"}],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [{"type": "bad"}],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [{"type": "text", "text": " "}],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "attachment_with_caption",
                    "parts": [{"type": "text", "text": "bad"}],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "attachment_with_caption",
                    "parts": [{"type": "attachment", "id": "a1"}],
                    "attachments": [
                        {
                            "id": "a1",
                            "file_path": "/tmp/a1.bin",
                            "mime_type": "application/octet-stream",
                            "metadata": {},
                            "caption": None,
                        }
                    ],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "attachment_with_caption",
                    "parts": [],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [
                        {
                            "type": "attachment",
                            "id": "a1",
                            "metadata": [],
                        }
                    ],
                    "attachments": [
                        {
                            "id": "a1",
                            "file_path": "/tmp/a1.bin",
                            "mime_type": "application/octet-stream",
                            "metadata": {},
                            "caption": None,
                        }
                    ],
                }
            )

        self.client._media_max_attachments_per_message = 1  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            self.client._normalize_composed_metadata(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [
                        {"type": "attachment", "id": "a1"},
                        {"type": "attachment", "id": "a2"},
                    ],
                    "attachments": [
                        {
                            "id": "a1",
                            "file_path": "/tmp/a1.bin",
                            "mime_type": "application/octet-stream",
                            "metadata": {},
                            "caption": None,
                        },
                        {
                            "id": "a2",
                            "file_path": "/tmp/a2.bin",
                            "mime_type": "application/octet-stream",
                            "metadata": {},
                            "caption": None,
                        },
                    ],
                }
            )

        self.client._media_max_attachments_per_message = 10  # pylint: disable=protected-access
        normalized_with_none_metadata = self.client._normalize_composed_metadata(  # pylint: disable=protected-access
            {
                "composition_mode": "message_with_attachments",
                "parts": [{"type": "attachment", "id": "a1"}],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1.bin",
                        "mime_type": "application/octet-stream",
                        "metadata": None,
                        "caption": None,
                    }
                ],
            }
        )
        self.assertEqual(normalized_with_none_metadata["attachments"][0]["metadata"], {})

        normalized_with_part_metadata = self.client._normalize_composed_metadata(  # pylint: disable=protected-access
            {
                "composition_mode": "message_with_attachments",
                "parts": [
                    {
                        "type": "attachment",
                        "id": "a1",
                        "metadata": {"p": "v"},
                    }
                ],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1.bin",
                        "mime_type": "application/octet-stream",
                        "metadata": {"a": "b"},
                        "caption": None,
                    }
                ],
            }
        )
        self.assertEqual(
            normalized_with_part_metadata["parts"][0]["metadata"],
            {"p": "v"},
        )

        normalized_attachment_with_caption = self.client._normalize_composed_metadata(  # pylint: disable=protected-access
            {
                "composition_mode": "attachment_with_caption",
                "parts": [{"type": "attachment", "id": "a1", "caption": "caption"}],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1.bin",
                        "mime_type": "application/octet-stream",
                        "metadata": {},
                        "caption": "caption",
                    }
                ],
            }
        )
        self.assertEqual(
            normalized_attachment_with_caption["attachments"][0]["caption"],
            "caption",
        )

        normalized = self.client._normalize_composed_metadata(  # pylint: disable=protected-access
            {
                "composition_mode": "message_with_attachments",
                "parts": [{"type": "text", "text": "ok"}],
                "attachments": [],
                "metadata": {"k": "v"},
            }
        )
        self.assertEqual(normalized["metadata"], {"k": "v"})
        self.assertGreater(self.client.media_max_attachments_per_message, 0)

    async def test_claim_and_subscriber_edge_branches(self) -> None:
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
                {
                    "version": 1,
                    "jobs": [
                        {"id": "a", "status": "done"},
                        {
                            "id": "b",
                            "status": "processing",
                            "lease_expires_at": 0,
                        },
                        {
                            "id": "c",
                            "status": "processing",
                            "lease_expires_at": 9999999999,
                        },
                    ],
                }
            )
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertIsNotNone(claimed)

        # Register twice to hit existing-conversation branch.
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        self.client._sse_max_subscribers_per_conversation = 2  # pylint: disable=protected-access
        await self.client._register_subscriber("conv-sub", q1)  # pylint: disable=protected-access
        await self.client._register_subscriber("conv-sub", q2)  # pylint: disable=protected-access
        await self.client._register_subscriber("conv-sub", q1)  # pylint: disable=protected-access
        q3 = asyncio.Queue()
        with self.assertRaises(OverflowError):
            await self.client._register_subscriber("conv-sub", q3)  # pylint: disable=protected-access
        self.assertEqual(
            self.client._web_metrics["web.sse.subscriber_limit_exceeded"],  # pylint: disable=protected-access
            1,
        )
        await self.client._unregister_subscriber("conv-sub", q1)  # pylint: disable=protected-access
        await self.client._unregister_subscriber("conv-sub", q2)  # pylint: disable=protected-access

        # Force enqueue timeout and disconnect fallback branches.
        class _QueueAlwaysFull:
            async def put(self, _item):
                await asyncio.sleep(1)

            def put_nowait(self, _item):
                raise asyncio.QueueFull()

            def get_nowait(self):
                raise asyncio.QueueEmpty()

        class _QueueStillFull:
            def __init__(self):
                self.calls = 0
                self._drained = False

            async def put(self, _item):
                await asyncio.sleep(1)

            def put_nowait(self, _item):
                self.calls += 1
                if self._drained:
                    return
                raise asyncio.QueueFull()

            def get_nowait(self):
                if self._drained:
                    raise asyncio.QueueEmpty()
                self._drained = True
                return {"id": "x"}

        async with self.client._subscriber_lock:  # pylint: disable=protected-access
            self.client._subscribers["conv-full"] = {  # pylint: disable=protected-access
                _QueueAlwaysFull(),
                _QueueStillFull(),
            }
        await self.client._publish_event("conv-full", {"id": "2"})  # pylint: disable=protected-access
        self.assertGreaterEqual(
            self.client._web_metrics["web.sse.fanout.publish_calls"],  # pylint: disable=protected-access
            1,
        )
        self.assertGreaterEqual(
            self.client._web_metrics["web.sse.fanout.timed_out"],  # pylint: disable=protected-access
            1,
        )

    async def test_publish_cleanup_state_and_helper_branches(self) -> None:
        # _publish_event timeout branch.
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait({"id": "1"})
        async with self.client._subscriber_lock:  # pylint: disable=protected-access
            self.client._subscribers["conv-p"] = {queue}  # pylint: disable=protected-access
        await self.client._publish_event("conv-p", {"id": "2"})  # pylint: disable=protected-access

        # unregister when conversation missing.
        await self.client._unregister_subscriber("missing", asyncio.Queue())  # pylint: disable=protected-access

        # cleanup branches: non-prefix, invalid payload, not-file, getmtime/os.remove failures.
        media_dir = Path(self.client._media_storage_path)  # pylint: disable=protected-access
        media_dir.mkdir(parents=True, exist_ok=True)
        subdir = media_dir / "nested"
        subdir.mkdir(exist_ok=True)
        bad_file = media_dir / "bad.bin"
        bad_file.write_bytes(b"x")
        os.utime(bad_file, (0, 0))
        self.relational._state.media_tokens["invalid"] = {  # pylint: disable=protected-access
            "token": "invalid",
            "owner_user_id": "user-1",
            "conversation_id": "conv-p",
            "file_path": None,
            "mime_type": "application/octet-stream",
            "filename": "invalid.bin",
            "expires_at": self.client._to_utc_datetime(9999999999),  # pylint: disable=protected-access
        }
        self.relational._state.media_tokens["no-file"] = {  # pylint: disable=protected-access
            "token": "no-file",
            "owner_user_id": "user-1",
            "conversation_id": "conv-p",
            "file_path": None,
            "mime_type": "application/octet-stream",
            "filename": "no-file.bin",
            "expires_at": self.client._to_utc_datetime(9999999999),  # pylint: disable=protected-access
        }
        fresh_file = media_dir / "fresh.bin"
        fresh_file.write_bytes(b"x")
        with (
            patch("os.path.getmtime", side_effect=OSError()),
            patch("os.remove", side_effect=OSError()),
        ):
            await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        removable = media_dir / "remove.bin"
        removable.write_bytes(b"x")
        os.utime(removable, (0, 0))
        with patch("os.remove", side_effect=OSError()):
            await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        # listdir exception branch.
        no_dir_cfg = _build_config(basedir=self.tmpdir.name)
        no_dir_relational = _InMemoryWebRelationalGateway()
        no_dir_client = DefaultWebClient(
            config=no_dir_cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=no_dir_cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=no_dir_cfg,
                relational_storage_gateway=no_dir_relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        no_dir_client._media_storage_path = os.path.join(self.tmpdir.name, "absent")  # pylint: disable=protected-access
        await no_dir_client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        # age < retention branch.
        young_cfg = _build_config(basedir=self.tmpdir.name)
        young_relational = _InMemoryWebRelationalGateway()
        young_client = DefaultWebClient(
            config=young_cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=young_cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=young_cfg,
                relational_storage_gateway=young_relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        young_client._media_retention_seconds = 999999  # pylint: disable=protected-access
        young_client._media_storage_path = str(media_dir)  # pylint: disable=protected-access
        await young_client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        # _mark_job_status continue branch and done branch.
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
                {
                    "version": 1,
                    "jobs": [
                        {"id": "x", "status": "pending"},
                        {"id": "y", "status": "processing"},
                    ],
                }
            )
        await self.client._mark_job_status("y", status="done", error=None)  # pylint: disable=protected-access
        await self.client._mark_job_failed("missing", "boom")  # pylint: disable=protected-access

        async with self.client._storage_lock:  # pylint: disable=protected-access
            queue_state = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            self.assertEqual(queue_state["jobs"][1]["status"], "done")
            self.assertIn("completed_at", queue_state["jobs"][1])

        # recover stale keeps non-processing jobs untouched.
        async with self.client._storage_lock:  # pylint: disable=protected-access
            await self.client._recover_stale_processing_jobs_unlocked()  # pylint: disable=protected-access
            queue_state = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            queue_state["jobs"][0]["status"] = "processing"
            queue_state["jobs"][0]["lease_expires_at"] = 9999999999
            await self.client._write_queue_state_unlocked(queue_state)  # pylint: disable=protected-access
            await self.client._recover_stale_processing_jobs_unlocked()  # pylint: disable=protected-access

    async def test_state_and_config_helper_branches(self) -> None:
        # conversation owner branches.
        with self.assertRaises(KeyError):
            await self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-x",
                auth_user="user-1",
                create_if_missing=False,
            )

        await self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
            conversation_id="conv-x",
            auth_user="user-1",
            create_if_missing=True,
        )
        with self.assertRaises(PermissionError):
            await self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-x",
                auth_user="user-2",
                create_if_missing=False,
            )

        # read_queue_state on empty relational store.
        queue = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
        self.assertEqual(queue["jobs"], [])

        # read_event_log malformed relational state fields.
        self.relational._state.conversation_states["conv-e"] = {  # pylint: disable=protected-access
            "conversation_id": "conv-e",
            "owner_user_id": "user-1",
            "stream_generation": "gen-e",
            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            "next_event_id": "bad",
        }
        log = await self.client._read_event_log_unlocked("conv-e")  # pylint: disable=protected-access
        self.assertEqual(log["events"], [])
        self.assertEqual(log["next_event_id"], 1)

        self.relational._state.conversation_states["conv-e2"] = {  # pylint: disable=protected-access
            "conversation_id": "conv-e2",
            "owner_user_id": "user-1",
            "stream_generation": "gen-e2",
            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
            "next_event_id": -5,
        }
        log = await self.client._read_event_log_unlocked("conv-e2")  # pylint: disable=protected-access
        self.assertEqual(log["next_event_id"], 1)

        # resolve_allowed_mimetypes branches.
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.allowed_mimetypes = "bad"
        helper_relational = _InMemoryWebRelationalGateway()
        helper_client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=helper_relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        self.assertTrue(helper_client.media_allowed_mimetypes)
        cfg.web.media.allowed_mimetypes = [123, ""]
        helper_relational_2 = _InMemoryWebRelationalGateway()
        helper_client_2 = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=cfg,
                relational_storage_gateway=helper_relational_2,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        self.assertTrue(helper_client_2.media_allowed_mimetypes)

        self.assertFalse(self.client.mimetype_allowed(None))
        self.assertFalse(self.client.mimetype_allowed("audio/ogg"))
        self.assertTrue(self.client.mimetype_allowed("image/png"))

        abs_path = self.client._resolve_storage_path("/tmp/x")  # pylint: disable=protected-access
        self.assertEqual(abs_path, "/tmp/x")
        no_base_cfg = SimpleNamespace(
            rdbms=SimpleNamespace(
                migration_tracks=SimpleNamespace(
                    core=SimpleNamespace(schema="mugen"),
                )
            ),
            web=SimpleNamespace(media=SimpleNamespace()),
        )
        no_base_relational = _InMemoryWebRelationalGateway()
        no_base_client = DefaultWebClient(
            config=no_base_cfg,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=no_base_cfg,
                keyval_storage_gateway=_InMemoryKeyVal(),
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=no_base_cfg,
                relational_storage_gateway=no_base_relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        self.assertTrue(
            no_base_client._resolve_storage_path("rel/path").endswith("rel/path")  # pylint: disable=protected-access
        )
        no_base_client._ensure_media_directory()  # pylint: disable=protected-access

        # parse and coercion helpers.
        self.assertEqual(self.client._resolve_float_config(("missing",), 1.0, minimum=0.1), 1.0)  # pylint: disable=protected-access
        self.assertEqual(self.client._resolve_int_config(("missing",), 1, minimum=1), 1)  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "keepalive_seconds"):
            self.client._resolve_float_config(  # pylint: disable=protected-access
                ("web", "sse", "keepalive_seconds"),
                1.0,
                minimum=100.0,
            )
        self.assertEqual(
            self.client._resolve_int_config(("web", "queue", "max_pending_jobs"), 1, minimum=1000),  # pylint: disable=protected-access
            1,
        )
        self.assertEqual(self.client._resolve_str_config(("missing",), "d"), "d")  # pylint: disable=protected-access
        self.assertIsNone(self.client._resolve_config_path(("missing", "x")))  # pylint: disable=protected-access

        with self.assertRaises(ValueError):
            self.client._require_non_empty(1, "field")  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            self.client._require_non_empty(" ", "field")  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            self.client._normalize_message_type("bad")  # pylint: disable=protected-access

        self.assertIsNone(self.client._parse_event_id("x"))  # pylint: disable=protected-access
        self.assertIsNone(self.client._parse_event_id(-1))  # pylint: disable=protected-access
        formatted = self.client._format_sse_event({"id": "1", "event": "ack", "data": {"a": 1}})  # pylint: disable=protected-access
        self.assertIn("event: ack", formatted)

        self.assertIsNone(self.client._coerce_media_mime("no-slash"))  # pylint: disable=protected-access
        self.assertEqual(
            self.client._read_media_bytes(b"raw-bytes"),  # pylint: disable=protected-access
            b"raw-bytes",
        )
        self.assertEqual(
            self.client._read_media_bytes(bytearray(b"byte-array")),  # pylint: disable=protected-access
            b"byte-array",
        )
        self.assertEqual(
            self.client._read_media_bytes(memoryview(b"memory-view")),  # pylint: disable=protected-access
            b"memory-view",
        )

        class _NoRead(io.IOBase):
            read = None

        class _TellBad(io.IOBase):
            def read(self):
                return b"tell-bad"

            def tell(self):
                return "bad"

        class _ReadRaises(io.IOBase):
            def read(self):
                raise OSError("boom")

            def tell(self):
                return 0

        class _SeekRaises(io.IOBase):
            def read(self):
                return b"seek-raises"

            def tell(self):
                return 0

            def seek(self, _pos):
                raise OSError("seek")

        class _ReadByteArray(io.IOBase):
            def read(self):
                return bytearray(b"buffer")

        class _ReadMemoryView(io.IOBase):
            def read(self):
                return memoryview(b"mv")

        class _ReadStr(io.IOBase):
            def read(self):
                return "txt"

        class _ReadUnknown(io.IOBase):
            def read(self):
                return object()

        class _TellNotCallable(io.IOBase):
            tell = None

            def read(self):
                return b"tell-none"

        self.assertIsNone(
            self.client._read_media_bytes(_NoRead()),  # pylint: disable=protected-access
        )
        self.assertEqual(
            self.client._read_media_bytes(_TellBad()),  # pylint: disable=protected-access
            b"tell-bad",
        )
        self.assertIsNone(
            self.client._read_media_bytes(_ReadRaises()),  # pylint: disable=protected-access
        )
        self.assertEqual(
            self.client._read_media_bytes(_SeekRaises()),  # pylint: disable=protected-access
            b"seek-raises",
        )
        self.assertEqual(
            self.client._read_media_bytes(_ReadByteArray()),  # pylint: disable=protected-access
            b"buffer",
        )
        self.assertEqual(
            self.client._read_media_bytes(_ReadMemoryView()),  # pylint: disable=protected-access
            b"mv",
        )
        self.assertEqual(
            self.client._read_media_bytes(_ReadStr()),  # pylint: disable=protected-access
            b"txt",
        )
        self.assertIsNone(
            self.client._read_media_bytes(_ReadUnknown()),  # pylint: disable=protected-access
        )
        self.assertEqual(
            self.client._read_media_bytes(_TellNotCallable()),  # pylint: disable=protected-access
            b"tell-none",
        )

        self.client._media_storage_gateway.store_bytes = AsyncMock(return_value=None)  # pylint: disable=protected-access
        self.assertIsNone(
            await self.client._resolve_media_source_path(  # pylint: disable=protected-access
                file_path=b"payload",
                filename="payload.bin",
            )
        )

        self.client._media_storage_gateway.store_bytes = AsyncMock(  # pylint: disable=protected-access
            side_effect=OSError()
        )
        with self.assertRaises(OSError):
            await self.client._resolve_media_source_path(  # pylint: disable=protected-access
                file_path=b"payload",
                filename="payload.bin",
            )

        self.assertEqual(
            self.client._infer_media_extension(None),  # pylint: disable=protected-access
            "",
        )
        self.assertEqual(
            self.client._infer_media_extension("no-extension"),  # pylint: disable=protected-access
            "",
        )
        self.assertEqual(
            self.client._infer_media_extension("name.12345678901234567"),  # pylint: disable=protected-access
            "",
        )

    async def test_cleanup_media_tokens_cursor_cycle_and_non_prefix_keys(self) -> None:
        self.keyval.list_keys = AsyncMock()
        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        self.keyval.list_keys.assert_called()

    async def test_runtime_store_helper_raises_when_store_missing(self) -> None:
        self.client._web_runtime_store = None  # pylint: disable=protected-access
        with self.assertRaises(RuntimeError):
            self.client._runtime_store()  # pylint: disable=protected-access

    async def test_cleanup_media_tokens_skips_delete_when_expired_token_is_not_string(
        self,
    ) -> None:
        runtime_store = SimpleNamespace(
            list_media_tokens=AsyncMock(
                return_value=[
                    {
                        "token": None,
                        "expires_at": self.client._to_utc_datetime(0),  # pylint: disable=protected-access
                        "file_path": "ignored",
                    }
                ]
            ),
            delete_media_token=AsyncMock(),
            list_active_queue_payloads=AsyncMock(return_value=[]),
        )
        self.client._web_runtime_store = runtime_store  # pylint: disable=protected-access
        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access
        runtime_store.delete_media_token.assert_not_awaited()


class TestDefaultWebClientRelationalBranches(unittest.IsolatedAsyncioTestCase):
    """Covers relational web persistence branches with a stub SQL session."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.keyval = _InMemoryKeyVal()
        self.logger = Mock()
        self.messaging = SimpleNamespace(
            handle_text_message=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            handle_audio_message=AsyncMock(return_value=[]),
            handle_video_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_composed_message=AsyncMock(return_value=[{"type": "text", "content": "ok"}]),
            mh_extensions=[],
        )
        self.config = _build_config(basedir=self.tmpdir.name)
        self.relational = SimpleNamespace(
            raw_session=lambda: None,  # replaced per test
            check_readiness=lambda: None,
        )
        self.client = DefaultWebClient(
            config=self.config,
            ipc_service=Mock(),
            media_storage_gateway=_build_media_gateway(
                config=self.config,
                keyval_storage_gateway=self.keyval,
                logging_gateway=self.logger,
            ),
            web_runtime_store=_build_runtime_store(
                config=self.config,
                relational_storage_gateway=self.relational,
                logging_gateway=self.logger,
            ),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.tmpdir.cleanup()

    async def test_runtime_store_requirement_and_datetime_helpers(self) -> None:
        with self.assertRaisesRegex(ValueError, "web_runtime_store is required"):
            DefaultWebClient(
                config=self.config,
                ipc_service=Mock(),
                media_storage_gateway=_build_media_gateway(
                    config=self.config,
                    keyval_storage_gateway=self.keyval,
                    logging_gateway=self.logger,
                ),
                web_runtime_store=None,
                logging_gateway=self.logger,
                messaging_service=self.messaging,
                user_service=Mock(),
            )
        with self.assertRaisesRegex(ValueError, "media_storage_gateway is required"):
            DefaultWebClient(
                config=self.config,
                ipc_service=Mock(),
                media_storage_gateway=None,
                web_runtime_store=_build_runtime_store(
                    config=self.config,
                    relational_storage_gateway=self.relational,
                    logging_gateway=self.logger,
                ),
                logging_gateway=self.logger,
                messaging_service=self.messaging,
                user_service=Mock(),
            )

        dt = self.client._to_utc_datetime(self.client._epoch_now())  # pylint: disable=protected-access
        self.assertIsNotNone(self.client._datetime_to_epoch(dt))  # pylint: disable=protected-access
        naive_dt = self.client._iso_to_utc_datetime("2025-01-01T00:00:00")  # pylint: disable=protected-access
        self.assertIsNotNone(naive_dt)
        self.assertIsNotNone(
            self.client._datetime_to_epoch(naive_dt.replace(tzinfo=None))  # pylint: disable=protected-access
        )
        self.assertIsNone(self.client._datetime_to_epoch(None))  # pylint: disable=protected-access
        self.assertIsNone(self.client._iso_to_utc_datetime(None))  # pylint: disable=protected-access
        self.assertIsNone(self.client._iso_to_utc_datetime(""))  # pylint: disable=protected-access
        self.assertIsNone(self.client._iso_to_utc_datetime("not-a-date"))  # pylint: disable=protected-access
        self.assertIsNotNone(
            self.client._iso_to_utc_datetime("2025-01-01T00:00:00Z")  # pylint: disable=protected-access
        )

    async def test_tail_events_since_formats_tail_batch(self) -> None:
        tail_batch = WebRuntimeTailBatch(
            stream_generation="gen-x",
            max_event_id=9,
            requested_after_event_id=4,
            effective_after_event_id=4,
            first_event_id=7,
            events=[
                WebRuntimeTailEvent(
                    id=7,
                    event="system",
                    data={"ok": True},
                    created_at="2025-01-01T00:00:00+00:00",
                    stream_generation="gen-x",
                    stream_version=2,
                )
            ],
        )
        self.client._web_runtime_store.tail_events_since = AsyncMock(  # type: ignore[attr-defined]  # pylint: disable=protected-access
            return_value=tail_batch
        )

        payload = await self.client._tail_events_since(  # pylint: disable=protected-access
            conversation_id="conv-tail",
            stream_generation="gen-a",
            after_event_id=1,
        )

        self.assertEqual(payload["stream_generation"], "gen-x")
        self.assertEqual(payload["max_event_id"], 9)
        self.assertEqual(payload["requested_after_event_id"], 4)
        self.assertEqual(payload["effective_after_event_id"], 4)
        self.assertEqual(payload["first_event_id"], 7)
        self.assertEqual(payload["events"][0]["id"], "7")
        self.assertEqual(payload["events"][0]["event"], "system")
        self.assertEqual(payload["events"][0]["stream_version"], 2)

    async def test_enqueue_message_relational_overflow_and_success(self) -> None:
        self.client._queue_max_pending_jobs = 1  # pylint: disable=protected-access
        overflow_session = _SequenceSession(
            [
                _SequenceResult(rows=[{"owner_user_id": "user-1"}]),
                _SequenceResult(scalar_value=1),
            ]
        )
        _force_relational_session(self.client, overflow_session)
        self.client._append_event = AsyncMock(return_value={})  # pylint: disable=protected-access

        with self.assertRaises(OverflowError):
            await self.client.enqueue_message(
                auth_user="user-1",
                conversation_id="conv-r-1",
                message_type="text",
                text="hello",
            )

        success_session = _SequenceSession(
            [
                _SequenceResult(rows=[{"owner_user_id": "user-1"}]),
                _SequenceResult(scalar_value=0),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, success_session)
        payload = await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-r-1",
            message_type="text",
            text="hello",
        )
        self.assertEqual(payload["conversation_id"], "conv-r-1")
        self.assertEqual(len(success_session.calls), 3)

    async def test_resolve_media_download_relational_branches(self) -> None:
        now = self.client._epoch_now()  # pylint: disable=protected-access
        missing_session = _SequenceSession([_SequenceResult(rows=[])])
        _force_relational_session(self.client, missing_session)
        self.assertIsNone(
            await self.client.resolve_media_download(auth_user="u1", token="missing")
        )

        expired_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "token": "t1",
                            "owner_user_id": "u1",
                            "file_path": "/tmp/f.bin",
                            "mime_type": "text/plain",
                            "filename": "f.bin",
                            "expires_at": self.client._to_utc_datetime(now - 10),  # pylint: disable=protected-access
                        }
                    ]
                ),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, expired_session)
        self.assertIsNone(await self.client.resolve_media_download(auth_user="u1", token="t1"))

        owner_mismatch = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "token": "t2",
                            "owner_user_id": "u2",
                            "file_path": "/tmp/f.bin",
                            "mime_type": "text/plain",
                            "filename": "f.bin",
                            "expires_at": self.client._to_utc_datetime(now + 10),  # pylint: disable=protected-access
                        }
                    ]
                )
            ]
        )
        _force_relational_session(self.client, owner_mismatch)
        self.assertIsNone(await self.client.resolve_media_download(auth_user="u1", token="t2"))

        invalid_path_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "token": "t2b",
                            "owner_user_id": "u1",
                            "file_path": "",
                            "mime_type": "text/plain",
                            "filename": "f.bin",
                            "expires_at": self.client._to_utc_datetime(now + 10),  # pylint: disable=protected-access
                        }
                    ]
                )
            ]
        )
        _force_relational_session(self.client, invalid_path_session)
        self.assertIsNone(await self.client.resolve_media_download(auth_user="u1", token="t2b"))

        missing_path = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "token": "t3",
                            "owner_user_id": "u1",
                            "file_path": "/tmp/does-not-exist.bin",
                            "mime_type": "text/plain",
                            "filename": "f.bin",
                            "expires_at": self.client._to_utc_datetime(now + 10),  # pylint: disable=protected-access
                        }
                    ]
                ),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, missing_path)
        with patch("os.path.exists", return_value=False):
            self.assertIsNone(
                await self.client.resolve_media_download(auth_user="u1", token="t3")
            )

        valid_ref = await self.client._media_storage_gateway.store_bytes(  # pylint: disable=protected-access
            b"x",
            filename_hint="ok.bin",
        )
        assert isinstance(valid_ref, str)
        success_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "token": "t4",
                            "owner_user_id": "u1",
                            "file_path": valid_ref,
                            "mime_type": "application/octet-stream",
                            "filename": "ok.bin",
                            "expires_at": self.client._to_utc_datetime(now + 10),  # pylint: disable=protected-access
                        }
                    ]
                )
            ]
        )
        _force_relational_session(self.client, success_session)
        resolved = await self.client.resolve_media_download(auth_user="u1", token="t4")
        self.assertTrue(isinstance(resolved, dict))
        self.assertTrue(os.path.exists(str(resolved["file_path"])))

    async def test_claim_next_job_relational_branches(self) -> None:
        none_session = _SequenceSession(
            [
                _SequenceResult(),
                _SequenceResult(rows=[]),
            ]
        )
        _force_relational_session(self.client, none_session)
        self.assertIsNone(await self.client._claim_next_job())  # pylint: disable=protected-access

        update_none_session = _SequenceSession(
            [
                _SequenceResult(),
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "job-5",
                            "conversation_id": "conv-5",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hello"},
                            "status": "pending",
                            "attempts": 0,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-5",
                        }
                    ]
                ),
                _SequenceResult(rows=[]),
            ]
        )
        _force_relational_session(self.client, update_none_session)
        self.assertIsNone(await self.client._claim_next_job())  # pylint: disable=protected-access

        success_session = _SequenceSession(
            [
                _SequenceResult(),
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "job-8",
                            "conversation_id": "conv-8",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hello"},
                            "status": "pending",
                            "attempts": 0,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-8",
                        }
                    ]
                ),
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "job-8",
                            "conversation_id": "conv-8",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hello"},
                            "status": "processing",
                            "attempts": 1,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-8",
                        }
                    ]
                ),
            ]
        )
        _force_relational_session(self.client, success_session)
        claimed = await self.client._claim_next_job()  # pylint: disable=protected-access
        self.assertEqual(claimed["id"], "job-8")
        self.assertEqual(claimed["text"], "hello")

    async def test_claim_next_job_relational_logs_recovery_count(self) -> None:
        self.logger.reset_mock()
        recovery_session = _SequenceSession(
            [
                SimpleNamespace(rowcount=2),
                _SequenceResult(rows=[]),
            ]
        )
        _force_relational_session(self.client, recovery_session)
        self.assertIsNone(await self.client._claim_next_job())  # pylint: disable=protected-access
        self.logger.warning.assert_called_once()
        self.assertIn(
            "lease recovery reset stale jobs",
            str(self.logger.warning.call_args.args[0]),
        )

    async def test_mark_job_status_relational_returns_when_job_missing(self) -> None:
        missing_session = _SequenceSession([_SequenceResult(rows=[])])
        _force_relational_session(self.client, missing_session)
        await self.client._mark_job_done("missing")  # pylint: disable=protected-access
        self.assertEqual(len(missing_session.calls), 1)

    async def test_mark_job_status_relational_skips_invalid_terminal_transition(self) -> None:
        pending_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "job-pending",
                            "conversation_id": "conv-1",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hello"},
                            "status": "pending",
                            "attempts": 1,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-pending",
                        }
                    ]
                ),
            ]
        )
        _force_relational_session(self.client, pending_session)
        self.logger.reset_mock()
        await self.client._mark_job_done("job-pending")  # pylint: disable=protected-access

        self.assertEqual(len(pending_session.calls), 1)
        self.logger.warning.assert_called_once()
        self.assertIn(
            "violates lifecycle invariant",
            str(self.logger.warning.call_args.args[0]),
        )

    async def test_mark_job_status_relational_non_terminal_update_has_no_precondition(
        self,
    ) -> None:
        processing_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "job-processing",
                            "conversation_id": "conv-1",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hello"},
                            "status": "processing",
                            "attempts": 1,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-processing",
                        }
                    ]
                ),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, processing_session)
        await self.client._mark_job_status(  # pylint: disable=protected-access
            "job-processing",
            status="processing",
            error="still-running",
        )

        update_sql, update_params = processing_session.calls[1]
        self.assertIn("WHERE job_id = :job_id", update_sql)
        self.assertNotIn("current_status", update_params)

    async def test_mark_job_status_relational_warns_when_terminal_update_precondition_fails(
        self,
    ) -> None:
        precondition_fail_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "job-race",
                            "conversation_id": "conv-1",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hello"},
                            "status": "processing",
                            "attempts": 1,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-race",
                        }
                    ]
                ),
                SimpleNamespace(rowcount=0),
            ]
        )
        _force_relational_session(self.client, precondition_fail_session)
        self.logger.reset_mock()
        await self.client._mark_job_done(  # pylint: disable=protected-access
            "job-race",
            expected_attempt=2,
        )

        self.logger.warning.assert_called_once()
        self.assertIn(
            "precondition mismatch",
            str(self.logger.warning.call_args.args[0]),
        )
        self.assertEqual(precondition_fail_session.calls[1][1]["expected_attempt"], 2)

    async def test_persist_media_reference_does_not_delete_when_ref_unchanged(self) -> None:
        source_path = Path(self.tmpdir.name) / "keep.bin"
        source_path.write_bytes(b"x")

        with (
            patch.object(
                self.client,
                "_resolve_media_source_path",
                new=AsyncMock(return_value=str(source_path.resolve())),
            ),
            patch("os.remove") as remove_file,
        ):
            persisted = await self.client._persist_media_reference(  # pylint: disable=protected-access
                file_path=str(source_path),
                filename_hint="keep.bin",
            )

        self.assertEqual(persisted, str(source_path.resolve()))
        remove_file.assert_not_called()

    async def test_create_media_token_payload_and_append_event_relational(self) -> None:
        source_file = Path(self.tmpdir.name) / "source.bin"
        source_file.write_bytes(b"abc")

        token_session = _SequenceSession([_SequenceResult()])
        _force_relational_session(self.client, token_session)
        token_payload = await self.client._create_media_token_payload(  # pylint: disable=protected-access
            file_path=str(source_file),
            owner_user_id="u1",
            conversation_id="conv-token",
            mime_type="application/octet-stream",
            filename="source.bin",
        )
        self.assertTrue(token_payload["url"].startswith("/api/core/web/v1/media/"))

        append_session = _SequenceSession(
            [
                _SequenceResult(rows=[]),
                _SequenceResult(),
                _SequenceResult(
                    rows=[
                        {
                            "owner_user_id": "system",
                            "stream_generation": "",
                            "next_event_id": 0,
                        }
                    ]
                ),
                _SequenceResult(),
                _SequenceResult(),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, append_session)
        self.client._publish_event = AsyncMock()  # pylint: disable=protected-access
        event = await self.client._append_event(  # pylint: disable=protected-access
            conversation_id="conv-evt",
            event_type="message",
            data={"message": {"type": "text", "content": "hello"}},
        )
        self.assertEqual(event["id"], "1")

        append_existing_state = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "owner_user_id": "system",
                            "stream_generation": "gen-existing",
                            "next_event_id": "bad",
                        }
                    ]
                ),
                _SequenceResult(),
                _SequenceResult(),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, append_existing_state)
        event_from_existing = await self.client._append_event(  # pylint: disable=protected-access
            conversation_id="conv-evt-existing",
            event_type="system",
            data={"message": "ok"},
        )
        self.assertEqual(event_from_existing["id"], "1")

        append_existing_positive = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "owner_user_id": "system",
                            "stream_generation": "gen-existing",
                            "next_event_id": 2,
                        }
                    ]
                ),
                _SequenceResult(),
                _SequenceResult(),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, append_existing_positive)
        event_from_positive = await self.client._append_event(  # pylint: disable=protected-access
            conversation_id="conv-evt-positive",
            event_type="system",
            data={"message": "ok"},
        )
        self.assertEqual(event_from_positive["id"], "2")

        append_failure = _SequenceSession(
            [
                _SequenceResult(rows=[]),
                _SequenceResult(),
                _SequenceResult(rows=[]),
            ]
        )
        _force_relational_session(self.client, append_failure)
        with self.assertRaises(RuntimeError):
            await self.client._append_event(  # pylint: disable=protected-access
                conversation_id="conv-fail",
                event_type="message",
                data={"message": {"type": "text", "content": "x"}},
            )

    async def test_cleanup_media_relational_includes_queue_payload_refs(self) -> None:
        cleanup_session = _SequenceSession(
            [
                _SequenceResult(rows=[]),
                _SequenceResult(
                    rows=[
                        {
                            "payload": {
                                "file_path": "object:pending",
                                "metadata": {
                                    "attachments": [
                                        {"file_path": "object:attach-a"},
                                    ]
                                },
                            }
                        },
                        {
                            "payload": json.dumps(
                                {
                                    "file_path": "object:processing",
                                    "metadata": {
                                        "attachments": [
                                            {"file_path": "object:attach-b"},
                                        ]
                                    },
                                }
                            )
                        },
                    ]
                ),
            ]
        )
        _force_relational_session(self.client, cleanup_session)
        self.client._media_storage_gateway.cleanup = AsyncMock()  # pylint: disable=protected-access

        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        cleanup_kwargs = self.client._media_storage_gateway.cleanup.await_args.kwargs  # pylint: disable=protected-access
        active_refs = cleanup_kwargs["active_refs"]
        self.assertIn("object:pending", active_refs)
        self.assertIn("object:processing", active_refs)
        self.assertIn("object:attach-a", active_refs)
        self.assertIn("object:attach-b", active_refs)

    async def test_relational_queue_owner_cleanup_and_event_log_helpers(self) -> None:
        stale_ref = await self.client._media_storage_gateway.store_bytes(  # pylint: disable=protected-access
            b"s",
            filename_hint="stale.bin",
        )
        active_ref = await self.client._media_storage_gateway.store_bytes(  # pylint: disable=protected-access
            b"a",
            filename_hint="active.bin",
        )
        assert isinstance(stale_ref, str)
        assert isinstance(active_ref, str)
        stale_file = await self.client._media_storage_gateway.materialize(stale_ref)  # pylint: disable=protected-access
        active_file = await self.client._media_storage_gateway.materialize(active_ref)  # pylint: disable=protected-access
        assert isinstance(stale_file, str)
        assert isinstance(active_file, str)
        old = self.client._epoch_now() - 3600  # pylint: disable=protected-access
        os.utime(stale_file, (old, old))
        stale_object_id = stale_ref.split("object:", maxsplit=1)[1]
        await self.keyval.put_json(
            f"web:media:object:meta:{stale_object_id}",
            {"created_at": 0.0, "extension": ".bin"},
        )

        cleanup_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "token": "expired",
                            "file_path": stale_ref,
                            "expires_at": self.client._to_utc_datetime(old),  # pylint: disable=protected-access
                        },
                        {
                            "token": "active",
                            "file_path": active_ref,
                            "expires_at": self.client._to_utc_datetime(old + 7200),  # pylint: disable=protected-access
                        },
                        {
                            "token": "active-nopath",
                            "file_path": None,
                            "expires_at": self.client._to_utc_datetime(old + 7200),  # pylint: disable=protected-access
                        },
                    ]
                ),
                _SequenceResult(),
                _SequenceResult(rows=[]),
            ]
        )
        _force_relational_session(self.client, cleanup_session)
        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access
        self.assertTrue(Path(active_file).exists())
        self.assertFalse(Path(stale_file).exists())

        mark_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "job-1",
                            "conversation_id": "conv-1",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hello"},
                            "status": "processing",
                            "attempts": 1,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-1",
                        }
                    ]
                ),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, mark_session)
        await self.client._mark_job_done("job-1")  # pylint: disable=protected-access
        mark_sql, mark_params = mark_session.calls[1]
        self.assertIn(
            "SET status = :status",
            mark_sql,
        )
        self.assertIn(
            "AND status = :current_status",
            mark_sql,
        )
        self.assertIn("AND attempts = :expected_attempt", mark_sql)
        self.assertEqual(mark_params["status"], "done")
        self.assertEqual(mark_params["job_id"], "job-1")
        self.assertEqual(mark_params["current_status"], "processing")
        self.assertEqual(mark_params["expected_attempt"], 1)
        self.assertIsNone(mark_params["error_message"])
        self.assertIsNotNone(mark_params["completed_at"])

        failed_mark_session = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "job-2",
                            "conversation_id": "conv-1",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hello"},
                            "status": "processing",
                            "attempts": 1,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-1",
                        }
                    ]
                ),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, failed_mark_session)
        await self.client._mark_job_failed("job-2", "boom")  # pylint: disable=protected-access
        failed_sql, failed_params = failed_mark_session.calls[1]
        self.assertIn(
            "SET status = :status",
            failed_sql,
        )
        self.assertIn(
            "AND status = :current_status",
            failed_sql,
        )
        self.assertIn("AND attempts = :expected_attempt", failed_sql)
        self.assertEqual(failed_params["status"], "failed")
        self.assertEqual(failed_params["job_id"], "job-2")
        self.assertEqual(failed_params["current_status"], "processing")
        self.assertEqual(failed_params["expected_attempt"], 1)
        self.assertEqual(failed_params["error_message"], "boom")
        self.assertIsNotNone(failed_params["completed_at"])

        recovery_noop_session = _SequenceSession([SimpleNamespace(rowcount=0)])
        _force_relational_session(self.client, recovery_noop_session)
        await self.client._recover_stale_processing_jobs_unlocked()  # pylint: disable=protected-access

        recovery_warning = _SequenceSession([SimpleNamespace(rowcount=3)])
        _force_relational_session(self.client, recovery_warning)
        self.logger.reset_mock()
        await self.client._recover_stale_processing_jobs_unlocked()  # pylint: disable=protected-access
        self.logger.warning.assert_called_once()
        self.assertIn(
            "recovered stale processing jobs on startup",
            str(self.logger.warning.call_args.args[0]),
        )

        ensure_missing = _SequenceSession([_SequenceResult(rows=[])])
        _force_relational_session(self.client, ensure_missing)
        with self.assertRaises(KeyError):
            await self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-missing",
                auth_user="u1",
                create_if_missing=False,
            )

        ensure_fail = _SequenceSession(
            [
                _SequenceResult(rows=[]),
                _SequenceResult(),
                _SequenceResult(rows=[]),
            ]
        )
        _force_relational_session(self.client, ensure_fail)
        with self.assertRaises(RuntimeError):
            await self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-fail",
                auth_user="u1",
                create_if_missing=True,
            )

        ensure_mismatch = _SequenceSession(
            [_SequenceResult(rows=[{"owner_user_id": "other"}])]
        )
        _force_relational_session(self.client, ensure_mismatch)
        with self.assertRaises(PermissionError):
            await self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-own",
                auth_user="u1",
                create_if_missing=True,
            )

        read_queue = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "job_id": "jq-1",
                            "conversation_id": "cq-1",
                            "sender": "u1",
                            "message_type": "text",
                            "payload": {"text": "hi"},
                            "status": "pending",
                            "attempts": 0,
                            "created_at": None,
                            "updated_at": None,
                            "lease_expires_at": None,
                            "error_message": None,
                            "completed_at": None,
                            "client_message_id": "cid-1",
                        }
                    ]
                )
            ]
        )
        _force_relational_session(self.client, read_queue)
        queue_state = await self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
        self.assertEqual(queue_state["jobs"][0]["id"], "jq-1")

        write_queue = _SequenceSession([_SequenceResult(), _SequenceResult()])
        _force_relational_session(self.client, write_queue)
        await self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
            {
                "jobs": [
                    {
                        "id": "jq-2",
                        "conversation_id": "cq-2",
                        "sender": "u1",
                        "message_type": "text",
                        "text": "hello",
                        "metadata": {},
                        "status": "done",
                        "attempts": 1,
                        "lease_expires_at": None,
                        "error": "",
                        "completed_at": None,
                        "client_message_id": "",
                        "created_at": None,
                        "updated_at": None,
                    },
                    "bad-row",
                ]
            }
        )

        write_queue_non_list = _SequenceSession([_SequenceResult()])
        _force_relational_session(self.client, write_queue_non_list)
        await self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
            {"jobs": "bad-jobs"}
        )

        state_none = _SequenceSession([_SequenceResult(rows=[])])
        _force_relational_session(self.client, state_none)
        log_state = await self.client._read_event_log_unlocked("conv-log-none")  # pylint: disable=protected-access
        self.assertEqual(log_state["events"], [])

        state_mismatch = _SequenceSession(
            [_SequenceResult(rows=[{"stream_generation": "g", "stream_version": 999, "next_event_id": 1}])]
        )
        _force_relational_session(self.client, state_mismatch)
        reset_state = await self.client._read_event_log_unlocked("conv-log-mismatch")  # pylint: disable=protected-access
        self.assertEqual(reset_state["events"], [])

        state_bad_version = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "stream_generation": "g",
                            "stream_version": "bad",
                            "next_event_id": "bad",
                        }
                    ]
                )
            ]
        )
        _force_relational_session(self.client, state_bad_version)
        bad_version_state = await self.client._read_event_log_unlocked("conv-log-bad")  # pylint: disable=protected-access
        self.assertEqual(bad_version_state["events"], [])

        state_valid = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "stream_generation": "gen-a",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                            "next_event_id": 0,
                        }
                    ]
                ),
                _SequenceResult(
                    rows=[
                        {
                            "event_id": 2,
                            "event_type": "message",
                            "payload": {"message": {"type": "text", "content": "x"}},
                            "created_at": None,
                            "stream_generation": "gen-a",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        },
                        {
                            "event_id": 3,
                            "event_type": "system",
                            "payload": "bad-payload",
                            "created_at": None,
                            "stream_generation": "gen-a",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        },
                    ]
                ),
            ]
        )
        _force_relational_session(self.client, state_valid)
        valid_log = await self.client._read_event_log_unlocked("conv-log-valid")  # pylint: disable=protected-access
        self.assertEqual(valid_log["next_event_id"], 1)
        self.assertEqual(len(valid_log["events"]), 2)

        state_next_bad = _SequenceSession(
            [
                _SequenceResult(
                    rows=[
                        {
                            "stream_generation": "gen-b",
                            "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                            "next_event_id": "bad",
                        }
                    ]
                ),
                _SequenceResult(rows=[]),
            ]
        )
        _force_relational_session(self.client, state_next_bad)
        parsed_next_bad = await self.client._read_event_log_unlocked("conv-log-next-bad")  # pylint: disable=protected-access
        self.assertEqual(parsed_next_bad["next_event_id"], 1)

        write_log = _SequenceSession(
            [
                _SequenceResult(rows=[]),
                _SequenceResult(),
                _SequenceResult(),
                _SequenceResult(),
                _SequenceResult(),
            ]
        )
        _force_relational_session(self.client, write_log)
        await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
            "conv-write",
            {
                "generation": "",
                "next_event_id": 0,
                "events": [
                    "bad-event",
                    {"id": "x"},
                    {
                        "id": "1",
                        "event": "message",
                        "data": "not-dict",
                        "stream_generation": "",
                        "stream_version": None,
                        "created_at": None,
                    },
                    {
                        "id": "2",
                        "event": "system",
                        "data": {"ok": True},
                        "stream_generation": "gen",
                        "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                        "created_at": None,
                    },
                ],
            },
        )

        write_log_non_list = _SequenceSession(
            [_SequenceResult(), _SequenceResult(), _SequenceResult()]
        )
        _force_relational_session(self.client, write_log_non_list)
        await self.client._write_event_log_unlocked(  # pylint: disable=protected-access
            "conv-write-bad",
            {
                "generation": "gen",
                "next_event_id": "bad",
                "events": "bad-events",
            },
        )

    async def test_wait_until_stopped_guard_and_success_path(self) -> None:
        self.client._worker_task = None  # pylint: disable=protected-access
        with self.assertRaises(RuntimeError):
            await self.client.wait_until_stopped()

        task = asyncio.create_task(asyncio.sleep(0))
        self.client._worker_task = task  # pylint: disable=protected-access
        await self.client.wait_until_stopped()

    async def test_worker_done_callback_records_failure(self) -> None:
        async def _boom() -> None:
            raise RuntimeError("boom")

        task = asyncio.create_task(_boom())
        await asyncio.gather(task, return_exceptions=True)

        self.client._on_worker_task_done(task)  # pylint: disable=protected-access
        self.assertIsNotNone(self.client._worker_failure)  # pylint: disable=protected-access
        self.logger.error.assert_called_once()

    async def test_worker_done_callback_ignores_successful_completion(self) -> None:
        task = asyncio.create_task(asyncio.sleep(0))
        await task

        self.client._on_worker_task_done(task)  # pylint: disable=protected-access
        self.assertIsNone(self.client._worker_failure)  # pylint: disable=protected-access

    async def test_stream_events_early_timeout_without_ping_branch(self) -> None:
        self.client._sse_keepalive_seconds = 60.0  # pylint: disable=protected-access
        stream_generation = "timeout-gen"

        original_wait_for = web_mod.asyncio.wait_for
        first_timeout = {"pending": True}

        async def _early_timeout_once(awaitable, timeout):
            if first_timeout["pending"] is True:
                first_timeout["pending"] = False
                close_fn = getattr(awaitable, "close", None)
                if callable(close_fn):
                    close_fn()
                raise asyncio.TimeoutError()
            return await original_wait_for(awaitable, timeout)

        with (
            patch.object(
                self.client,
                "_ensure_conversation_owner_unlocked",
                new=AsyncMock(return_value="user-1"),
            ),
            patch.object(
                self.client,
                "_read_event_log_unlocked",
                new=AsyncMock(
                    return_value={
                        "version": self.client._event_log_version,  # pylint: disable=protected-access
                        "generation": stream_generation,
                        "next_event_id": 1,
                        "events": [],
                    }
                ),
            ),
            patch.object(
                self.client,
                "_ensure_cross_instance_poller",
                new=AsyncMock(return_value=None),
            ),
            patch.object(web_mod.asyncio, "wait_for", new=_early_timeout_once),
        ):
            async def _next_non_ping_local(stream_obj):
                for _ in range(10):
                    chunk = await stream_obj.__anext__()
                    if chunk != ": ping\n\n":
                        return chunk
                self.fail("Timed out waiting for non-ping SSE chunk.")

            stream = await self.client.stream_events(
                auth_user="user-1",
                conversation_id="conv-timeout-no-ping",
            )
            next_chunk = asyncio.create_task(_next_non_ping_local(stream))
            await asyncio.sleep(0)
            await self.client._publish_event(  # pylint: disable=protected-access
                "conv-timeout-no-ping",
                {
                    "id": "1",
                    "event": "system",
                    "data": {"message": "after-timeout"},
                    "stream_generation": stream_generation,
                    "stream_version": self.client._event_log_version,  # pylint: disable=protected-access
                },
            )
            chunk = await asyncio.wait_for(next_chunk, timeout=1.0)
            self.assertIn("after-timeout", chunk)
            await stream.aclose()

    async def test_ensure_cross_instance_poller_reuses_active_pending_task(self) -> None:
        blocker = asyncio.Event()
        pending_task = asyncio.create_task(blocker.wait())
        self.client._sse_cross_instance_pollers["conv-active"] = (  # pylint: disable=protected-access
            pending_task,
            asyncio.Event(),
        )

        with patch.object(
            self.client,
            "_resolve_cross_instance_poll_cursor",
            new=AsyncMock(),
        ) as resolve_cursor:
            await self.client._ensure_cross_instance_poller(  # pylint: disable=protected-access
                "conv-active"
            )
            resolve_cursor.assert_not_called()

        pending_task.cancel()
        await asyncio.gather(pending_task, return_exceptions=True)
        self.client._sse_cross_instance_pollers.clear()  # pylint: disable=protected-access

    async def test_ensure_cross_instance_poller_restarts_when_existing_task_done(
        self,
    ) -> None:
        finished_task = asyncio.create_task(asyncio.sleep(0))
        await finished_task
        self.client._sse_cross_instance_pollers["conv-restart"] = (  # pylint: disable=protected-access
            finished_task,
            asyncio.Event(),
        )

        with (
            patch.object(
                self.client,
                "_resolve_cross_instance_poll_cursor",
                new=AsyncMock(return_value=("restart-gen", 3)),
            ) as resolve_cursor,
            patch.object(
                self.client,
                "_cross_instance_poller_loop",
                new=AsyncMock(return_value=None),
            ),
        ):
            await self.client._ensure_cross_instance_poller(  # pylint: disable=protected-access
                "conv-restart"
            )
            resolve_cursor.assert_awaited_once_with("conv-restart")

        new_task, _stop_event = self.client._sse_cross_instance_pollers["conv-restart"]  # pylint: disable=protected-access
        await asyncio.gather(new_task, return_exceptions=True)
        self.client._sse_cross_instance_pollers.clear()  # pylint: disable=protected-access

    async def test_cross_instance_poller_loop_stop_event_paths(self) -> None:
        # Cover wait-for-stop continue path.
        self.client._sse_cross_instance_poll_seconds = 60.0  # pylint: disable=protected-access
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            self.client._cross_instance_poller_loop(  # pylint: disable=protected-access
                conversation_id="conv-stop-wait",
                initial_stream_generation="gen",
                initial_highest_event_id=0,
                stop_event=stop_event,
            )
        )
        await asyncio.sleep(0)
        stop_event.set()
        await asyncio.wait_for(task, timeout=1.0)

        # Cover pre-set stop condition and current-task cleanup pop path.
        preset_stop_event = asyncio.Event()
        preset_stop_event.set()
        current_task = asyncio.current_task()
        self.assertIsNotNone(current_task)
        self.client._sse_cross_instance_pollers["conv-current-task"] = (  # pylint: disable=protected-access
            current_task,
            preset_stop_event,
        )
        await self.client._cross_instance_poller_loop(  # pylint: disable=protected-access
            conversation_id="conv-current-task",
            initial_stream_generation="gen",
            initial_highest_event_id=0,
            stop_event=preset_stop_event,
        )
        self.assertNotIn(
            "conv-current-task",
            self.client._sse_cross_instance_pollers,  # pylint: disable=protected-access
        )

    async def test_cross_instance_poller_loop_keeps_mapping_for_foreign_task(self) -> None:
        foreign_task = asyncio.create_task(asyncio.sleep(0))
        await foreign_task
        stop_event = asyncio.Event()
        stop_event.set()
        self.client._sse_cross_instance_pollers["conv-foreign-task"] = (  # pylint: disable=protected-access
            foreign_task,
            stop_event,
        )

        await self.client._cross_instance_poller_loop(  # pylint: disable=protected-access
            conversation_id="conv-foreign-task",
            initial_stream_generation="gen",
            initial_highest_event_id=0,
            stop_event=stop_event,
        )
        self.assertIn(
            "conv-foreign-task",
            self.client._sse_cross_instance_pollers,  # pylint: disable=protected-access
        )
        self.client._sse_cross_instance_pollers.clear()  # pylint: disable=protected-access

    async def test_stop_cross_instance_poller_handles_missing_and_done_tasks(self) -> None:
        await self.client._stop_cross_instance_poller("conv-missing")  # pylint: disable=protected-access

        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        self.client._sse_cross_instance_pollers["conv-done"] = (  # pylint: disable=protected-access
            done_task,
            asyncio.Event(),
        )
        await self.client._stop_cross_instance_poller("conv-done")  # pylint: disable=protected-access
        self.assertNotIn(
            "conv-done",
            self.client._sse_cross_instance_pollers,  # pylint: disable=protected-access
        )

    async def test_stop_all_cross_instance_pollers_cleans_done_and_pending_tasks(
        self,
    ) -> None:
        blocker = asyncio.Event()
        pending_task = asyncio.create_task(blocker.wait())
        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        self.client._sse_cross_instance_pollers = {  # pylint: disable=protected-access
            "conv-pending": (pending_task, asyncio.Event()),
            "conv-done": (done_task, asyncio.Event()),
        }

        await self.client._stop_all_cross_instance_pollers()  # pylint: disable=protected-access
        self.assertEqual(
            self.client._sse_cross_instance_pollers,  # pylint: disable=protected-access
            {},
        )
        self.assertTrue(pending_task.done())

    async def test_stop_all_cross_instance_pollers_keeps_replaced_task_mapping(
        self,
    ) -> None:
        blocker = asyncio.Event()
        original_task = asyncio.create_task(blocker.wait())
        replacement_task = asyncio.create_task(asyncio.sleep(0))
        await replacement_task
        self.client._sse_cross_instance_pollers = {  # pylint: disable=protected-access
            "conv-replaced": (original_task, asyncio.Event())
        }

        async def _cancel_and_replace(task, *, task_name):  # noqa: ARG001
            self.client._sse_cross_instance_pollers["conv-replaced"] = (  # pylint: disable=protected-access
                replacement_task,
                asyncio.Event(),
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        with patch.object(
            self.client,
            "_cancel_task_with_timeout",
            new=AsyncMock(side_effect=_cancel_and_replace),
        ):
            await self.client._stop_all_cross_instance_pollers()  # pylint: disable=protected-access

        self.assertIs(
            self.client._sse_cross_instance_pollers["conv-replaced"][0],  # pylint: disable=protected-access
            replacement_task,
        )

    async def test_cancel_task_with_timeout_raises_on_timeout(self) -> None:
        pending_task = asyncio.create_task(asyncio.sleep(60))
        self.client._shutdown_timeout_seconds = 0.01  # pylint: disable=protected-access

        def _raise_timeout(awaitable, timeout):  # noqa: ARG001
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError

        with (
            patch(
                "mugen.core.client.web.asyncio.wait_for",
                side_effect=_raise_timeout,
            ),
            self.assertRaisesRegex(RuntimeError, "Web client shutdown timed out"),
        ):
            await self.client._cancel_task_with_timeout(  # pylint: disable=protected-access
                pending_task,
                task_name="worker",
            )

        self.assertTrue(
            any(
                "Web client shutdown timed out" in str(call.args[0])
                for call in self.client._logging_gateway.warning.call_args_list  # pylint: disable=protected-access
            )
        )
        pending_task.cancel()
        await asyncio.gather(pending_task, return_exceptions=True)

    def test_ensure_media_directory_creates_storage_path(self) -> None:
        temp_dir = os.path.join(self.tmpdir.name, "media-test")
        self.client._media_storage_path = temp_dir  # pylint: disable=protected-access
        self.client._ensure_media_directory()  # pylint: disable=protected-access
        self.assertTrue(os.path.isdir(temp_dir))
