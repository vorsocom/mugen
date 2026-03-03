"""Relational implementation of the web runtime persistence store."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from typing import Any
import uuid

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.web_runtime import (
    IWebRuntimeStore,
    WebRuntimeTailBatch,
    WebRuntimeTailEvent,
)
from mugen.core.domain.use_case.queue_job_lifecycle import QueueJobLifecycleUseCase
from mugen.core.gateway.storage.rdbms.sqla.shared_runtime import SharedSQLAlchemyRuntime
from mugen.core.gateway.storage.web_runtime.sql import text as web_sql_text
from mugen.core.utility.rdbms_schema import resolve_core_rdbms_schema
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker


class RelationalWebRuntimeStore(IWebRuntimeStore):
    """SQL-backed web runtime queue/event/media-token persistence."""

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
        relational_runtime: SharedSQLAlchemyRuntime,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._runtime = relational_runtime
        self._core_schema = resolve_core_rdbms_schema(config)
        self._queue_job_lifecycle_use_case = QueueJobLifecycleUseCase()
        self._engine = self._runtime.engine

        session_maker: async_sessionmaker = self._runtime.session_maker

        @asynccontextmanager
        async def _session_provider():
            async with session_maker() as session:
                async with session.begin():
                    yield session

        self._session_provider = _session_provider

    @asynccontextmanager
    async def _relational_session(self):
        async with self._session_provider() as session:
            yield session

    def _schema_sql(self, statement: str):
        return web_sql_text(statement.replace("mugen.", f"{self._core_schema}."))

    async def aclose(self) -> None:
        return None

    async def check_readiness(self) -> None:
        if self._engine is not None:
            async with self._engine.connect() as conn:
                await conn.execute(sa_text("SELECT 1"))

        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT "
                    "to_regclass('mugen.web_queue_job') AS web_queue_job, "
                    "to_regclass('mugen.web_conversation_state') AS web_conversation_state, "
                    "to_regclass('mugen.web_conversation_event') AS web_conversation_event, "
                    "to_regclass('mugen.web_media_token') AS web_media_token"
                )
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise RuntimeError("Web runtime relational readiness query failed.")
            missing = [
                name
                for name in (
                    "web_queue_job",
                    "web_conversation_state",
                    "web_conversation_event",
                    "web_media_token",
                )
                if row.get(name) in [None, ""]
            ]
            if missing:
                missing_text = ", ".join(sorted(missing))
                raise RuntimeError(
                    "Database schema is not ready. "
                    "Run migrations before startup. "
                    "Missing web runtime table(s): "
                    f"{missing_text}."
                )

    @staticmethod
    def _to_utc_datetime(epoch_seconds: float) -> datetime:
        return datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc)

    @staticmethod
    def _datetime_to_epoch(value: datetime | None) -> float | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    @staticmethod
    def _datetime_to_iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _iso_to_utc_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if candidate == "":
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _new_stream_generation() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def _normalize_stream_generation(value: Any, *, fallback: str) -> str:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized != "":
                return normalized.replace(":", "-")
        return fallback

    @staticmethod
    def _parse_event_id(value: Any) -> int | None:
        if value in [None, ""]:
            return None

        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return None

        if parsed < 0:
            return None

        return parsed

    @staticmethod
    def _queue_job_record_to_payload(row: Any) -> dict[str, Any]:
        if hasattr(row, "get") and callable(row.get):
            getter = row.get
        else:
            getter = lambda key, default=None: getattr(row, key, default)

        payload = getter("payload")
        if not isinstance(payload, dict):
            payload = {}
        return {
            "id": getter("job_id"),
            "conversation_id": getter("conversation_id"),
            "sender": getter("sender"),
            "message_type": getter("message_type"),
            "text": payload.get("text"),
            "metadata": payload.get("metadata"),
            "file_path": payload.get("file_path"),
            "mime_type": payload.get("mime_type"),
            "original_filename": payload.get("original_filename"),
            "client_message_id": getter("client_message_id"),
            "status": getter("status"),
            "attempts": int(getter("attempts") or 0),
            "created_at": RelationalWebRuntimeStore._datetime_to_iso(getter("created_at")),
            "updated_at": RelationalWebRuntimeStore._datetime_to_iso(getter("updated_at")),
            "lease_expires_at": RelationalWebRuntimeStore._datetime_to_epoch(
                getter("lease_expires_at")
            ),
            "error": getter("error_message"),
            "completed_at": RelationalWebRuntimeStore._datetime_to_iso(
                getter("completed_at")
            ),
        }

    @staticmethod
    def _new_event_log_state(event_log_version: int) -> dict[str, Any]:
        return {
            "version": event_log_version,
            "generation": RelationalWebRuntimeStore._new_stream_generation(),
            "next_event_id": 1,
            "events": [],
        }

    async def ensure_conversation_owner(
        self,
        *,
        conversation_id: str,
        auth_user: str,
        create_if_missing: bool,
        stream_generation: str,
        stream_version: int,
    ) -> None:
        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT owner_user_id "
                    "FROM mugen.web_conversation_state "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            row = result.mappings().one_or_none()
            if row is None:
                if create_if_missing is not True:
                    raise KeyError("conversation not found")

                await session.execute(
                    self._schema_sql(
                        "INSERT INTO mugen.web_conversation_state "
                        "("
                        "conversation_id, owner_user_id, stream_generation, "
                        "stream_version, next_event_id, created_at, updated_at"
                        ") "
                        "VALUES ("
                        ":conversation_id, :owner_user_id, :stream_generation, "
                        ":stream_version, 1, now(), now()"
                        ") "
                        "ON CONFLICT (conversation_id) DO NOTHING"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "owner_user_id": auth_user,
                        "stream_generation": stream_generation,
                        "stream_version": stream_version,
                    },
                )

                result = await session.execute(
                    self._schema_sql(
                        "SELECT owner_user_id "
                        "FROM mugen.web_conversation_state "
                        "WHERE conversation_id = :conversation_id"
                    ),
                    {"conversation_id": conversation_id},
                )
                row = result.mappings().one_or_none()

            if row is None:
                raise RuntimeError(
                    f"Failed to ensure web conversation ownership ({conversation_id})."
                )

            if row.get("owner_user_id") != auth_user:
                raise PermissionError("conversation owner mismatch")

    async def count_pending_jobs(self) -> int:
        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT count(*) "
                    "FROM mugen.web_queue_job "
                    "WHERE status = 'pending'"
                )
            )
            return int(result.scalar() or 0)

    async def insert_pending_job(
        self,
        *,
        job_id: str,
        conversation_id: str,
        sender: str,
        message_type: str,
        payload: dict[str, Any],
        client_message_id: str,
    ) -> None:
        async with self._relational_session() as session:
            await session.execute(
                self._schema_sql(
                    "INSERT INTO mugen.web_queue_job "
                    "("
                    "job_id, conversation_id, sender, message_type, payload, "
                    "status, attempts, lease_expires_at, error_message, "
                    "completed_at, client_message_id, created_at, updated_at"
                    ") "
                    "VALUES ("
                    ":job_id, :conversation_id, :sender, :message_type, "
                    "CAST(:payload AS jsonb), 'pending', 0, NULL, NULL, NULL, "
                    ":client_message_id, now(), now()"
                    ")"
                ),
                {
                    "job_id": job_id,
                    "conversation_id": conversation_id,
                    "sender": sender,
                    "message_type": message_type,
                    "payload": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                    "client_message_id": client_message_id,
                },
            )

    async def claim_next_job(
        self,
        *,
        now_iso: str,
        now_epoch: float,
        queue_processing_lease_seconds: float,
    ) -> tuple[dict[str, Any] | None, int]:
        async with self._relational_session() as session:
            recovered_result = await session.execute(
                self._schema_sql(
                    "UPDATE mugen.web_queue_job "
                    "SET status = 'pending', lease_expires_at = NULL, updated_at = now() "
                    "WHERE status = 'processing' "
                    "AND (lease_expires_at IS NULL OR lease_expires_at <= now())"
                )
            )
            recovered_count = int(getattr(recovered_result, "rowcount", 0) or 0)

            selected = await session.execute(
                self._schema_sql(
                    "SELECT job_id, conversation_id, sender, message_type, payload, "
                    "status, attempts, created_at, updated_at, lease_expires_at, "
                    "error_message, completed_at, client_message_id "
                    "FROM mugen.web_queue_job "
                    "WHERE status = 'pending' "
                    "ORDER BY created_at ASC "
                    "FOR UPDATE SKIP LOCKED "
                    "LIMIT 1"
                )
            )
            selected_row = selected.mappings().one_or_none()
            if selected_row is None:
                return None, recovered_count

            selected_job = self._queue_job_record_to_payload(selected_row)
            claimed_view = self._queue_job_lifecycle_use_case.claim(
                job=selected_job,
                now_iso=now_iso,
                lease_expires_at=(now_epoch + queue_processing_lease_seconds),
            )
            updated = await session.execute(
                self._schema_sql(
                    "UPDATE mugen.web_queue_job "
                    "SET status = :status, "
                    "attempts = :attempts, "
                    "updated_at = :updated_at, "
                    "lease_expires_at = :lease_expires_at, "
                    "error_message = :error_message, "
                    "completed_at = :completed_at "
                    "WHERE job_id = :job_id "
                    "RETURNING job_id, conversation_id, sender, message_type, payload, "
                    "status, attempts, created_at, updated_at, lease_expires_at, "
                    "error_message, completed_at, client_message_id"
                ),
                {
                    "status": claimed_view.get("status"),
                    "attempts": int(claimed_view.get("attempts") or 0),
                    "updated_at": (
                        self._iso_to_utc_datetime(claimed_view.get("updated_at"))
                        or self._to_utc_datetime(now_epoch)
                    ),
                    "lease_expires_at": (
                        self._to_utc_datetime(float(claimed_view.get("lease_expires_at")))
                        if self._coerce_float(claimed_view.get("lease_expires_at"))
                        is not None
                        else None
                    ),
                    "error_message": (
                        str(claimed_view.get("error"))
                        if claimed_view.get("error") not in [None, ""]
                        else None
                    ),
                    "completed_at": self._iso_to_utc_datetime(
                        claimed_view.get("completed_at")
                    ),
                    "job_id": str(selected_row.get("job_id")),
                },
            )
            row = updated.mappings().one_or_none()
            if row is None:
                return None, recovered_count
            return self._queue_job_record_to_payload(row), recovered_count

    async def processing_owner_matches(
        self,
        *,
        job_id: str,
        expected_attempt: int,
    ) -> bool:
        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT status, attempts "
                    "FROM mugen.web_queue_job "
                    "WHERE job_id = :job_id"
                ),
                {"job_id": job_id},
            )
            row = result.mappings().one_or_none()
        if row is None:
            return False
        return (
            str(row.get("status", "")).strip().lower() == "processing"
            and int(row.get("attempts") or 0) == int(expected_attempt)
        )

    async def renew_processing_lease(
        self,
        *,
        job_id: str,
        expected_attempt: int | None,
        lease_expires_at: datetime,
        updated_at: datetime,
    ) -> bool:
        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "UPDATE mugen.web_queue_job "
                    "SET lease_expires_at = :lease_expires_at, "
                    "updated_at = :updated_at "
                    "WHERE job_id = :job_id "
                    "AND status = :current_status "
                    "AND (:expected_attempt IS NULL OR attempts = :expected_attempt)"
                ),
                {
                    "lease_expires_at": lease_expires_at,
                    "updated_at": updated_at,
                    "job_id": job_id,
                    "current_status": "processing",
                    "expected_attempt": (
                        int(expected_attempt) if expected_attempt is not None else None
                    ),
                },
            )
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def append_event(
        self,
        *,
        conversation_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: datetime,
        event_log_version: int,
        replay_max_events: int,
        new_stream_generation: str,
    ) -> dict[str, Any]:
        async with self._relational_session() as session:
            state_result = await session.execute(
                self._schema_sql(
                    "SELECT owner_user_id, stream_generation, next_event_id "
                    "FROM mugen.web_conversation_state "
                    "WHERE conversation_id = :conversation_id "
                    "FOR UPDATE"
                ),
                {"conversation_id": conversation_id},
            )
            state = state_result.mappings().one_or_none()
            if state is None:
                await session.execute(
                    self._schema_sql(
                        "INSERT INTO mugen.web_conversation_state "
                        "("
                        "conversation_id, owner_user_id, stream_generation, "
                        "stream_version, next_event_id, created_at, updated_at"
                        ") "
                        "VALUES ("
                        ":conversation_id, 'system', :stream_generation, "
                        ":stream_version, 1, now(), now()"
                        ") "
                        "ON CONFLICT (conversation_id) DO NOTHING"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "stream_generation": self._new_stream_generation(),
                        "stream_version": event_log_version,
                    },
                )
                state_result = await session.execute(
                    self._schema_sql(
                        "SELECT owner_user_id, stream_generation, next_event_id "
                        "FROM mugen.web_conversation_state "
                        "WHERE conversation_id = :conversation_id "
                        "FOR UPDATE"
                    ),
                    {"conversation_id": conversation_id},
                )
                state = state_result.mappings().one_or_none()
                if state is None:
                    raise RuntimeError(
                        f"Unable to initialize web conversation state ({conversation_id})."
                    )

            stream_generation = self._normalize_stream_generation(
                state.get("stream_generation"),
                fallback=new_stream_generation,
            )
            try:
                event_id = int(state.get("next_event_id"))
            except (TypeError, ValueError):
                event_id = 1
            if event_id <= 0:
                event_id = 1

            await session.execute(
                self._schema_sql(
                    "INSERT INTO mugen.web_conversation_event "
                    "("
                    "conversation_id, event_id, event_type, payload, "
                    "stream_generation, stream_version, created_at, updated_at"
                    ") "
                    "VALUES ("
                    ":conversation_id, :event_id, :event_type, CAST(:payload AS jsonb), "
                    ":stream_generation, :stream_version, :created_at, now()"
                    ")"
                ),
                {
                    "conversation_id": conversation_id,
                    "event_id": event_id,
                    "event_type": event_type,
                    "payload": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                    "stream_generation": stream_generation,
                    "stream_version": event_log_version,
                    "created_at": created_at,
                },
            )

            await session.execute(
                self._schema_sql(
                    "UPDATE mugen.web_conversation_state "
                    "SET next_event_id = :next_event_id, "
                    "stream_generation = :stream_generation, "
                    "stream_version = :stream_version, "
                    "updated_at = now() "
                    "WHERE conversation_id = :conversation_id"
                ),
                {
                    "next_event_id": event_id + 1,
                    "stream_generation": stream_generation,
                    "stream_version": event_log_version,
                    "conversation_id": conversation_id,
                },
            )

            min_keep_event_id = max(event_id - replay_max_events + 1, 1)
            await session.execute(
                self._schema_sql(
                    "DELETE FROM mugen.web_conversation_event "
                    "WHERE conversation_id = :conversation_id "
                    "AND event_id < :min_keep_event_id"
                ),
                {
                    "conversation_id": conversation_id,
                    "min_keep_event_id": min_keep_event_id,
                },
            )

        return {
            "id": str(event_id),
            "event": event_type,
            "data": payload,
            "created_at": self._datetime_to_iso(created_at),
            "stream_generation": stream_generation,
            "stream_version": event_log_version,
        }

    async def list_media_tokens(self) -> list[dict[str, Any]]:
        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT token, file_path, expires_at "
                    "FROM mugen.web_media_token"
                )
            )
            return [dict(row) for row in result.mappings().all()]

    async def tail_events_since(
        self,
        *,
        conversation_id: str,
        stream_generation: str | None,
        after_event_id: int,
        limit: int,
    ) -> WebRuntimeTailBatch:
        normalized_limit = max(1, min(int(limit), 500))
        normalized_after_event_id = max(int(after_event_id), 0)
        fallback_generation = self._normalize_stream_generation(
            stream_generation,
            fallback=self._new_stream_generation(),
        )

        async with self._relational_session() as session:
            state_result = await session.execute(
                self._schema_sql(
                    "SELECT stream_generation "
                    "FROM mugen.web_conversation_state "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            state_row = state_result.mappings().one_or_none()
            active_generation = self._normalize_stream_generation(
                None if state_row is None else state_row.get("stream_generation"),
                fallback=fallback_generation,
            )

            effective_after_event_id = normalized_after_event_id
            if (
                isinstance(stream_generation, str)
                and stream_generation.strip() != ""
                and active_generation != stream_generation.strip()
            ):
                # Generation changed across instances; force replay from stream head.
                effective_after_event_id = 0

            events_result = await session.execute(
                self._schema_sql(
                    "SELECT event_id, event_type, payload, created_at, stream_generation, "
                    "stream_version "
                    "FROM mugen.web_conversation_event "
                    "WHERE conversation_id = :conversation_id "
                    "AND stream_generation = :stream_generation "
                    "AND event_id > :after_event_id "
                    "ORDER BY event_id ASC "
                    "LIMIT :limit"
                ),
                {
                    "conversation_id": conversation_id,
                    "stream_generation": active_generation,
                    "after_event_id": effective_after_event_id,
                    "limit": normalized_limit,
                },
            )
            rows = list(events_result.mappings().all())

        events: list[WebRuntimeTailEvent] = []
        max_event_id = effective_after_event_id
        for row in rows:
            event_id = self._parse_event_id(row.get("event_id"))
            if event_id is None:
                continue
            max_event_id = max(max_event_id, event_id)
            payload = row.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            try:
                stream_version = int(row.get("stream_version") or 1)
            except (TypeError, ValueError):
                stream_version = 1
            events.append(
                WebRuntimeTailEvent(
                    id=event_id,
                    event=str(row.get("event_type") or ""),
                    data=payload,
                    created_at=self._datetime_to_iso(row.get("created_at")),
                    stream_generation=self._normalize_stream_generation(
                        row.get("stream_generation"),
                        fallback=active_generation,
                    ),
                    stream_version=stream_version,
                )
            )

        return WebRuntimeTailBatch(
            stream_generation=active_generation,
            max_event_id=max_event_id,
            events=events,
        )

    async def delete_media_token(self, *, token: str) -> None:
        async with self._relational_session() as session:
            await session.execute(
                self._schema_sql(
                    "DELETE FROM mugen.web_media_token "
                    "WHERE token = :token"
                ),
                {"token": token},
            )

    async def list_active_queue_payloads(self) -> list[Any]:
        async with self._relational_session() as session:
            queue_result = await session.execute(
                self._schema_sql(
                    "SELECT payload "
                    "FROM mugen.web_queue_job "
                    "WHERE status IN ('pending', 'processing')"
                )
            )
            return [row.get("payload") for row in queue_result.mappings().all()]

    async def insert_media_token(
        self,
        *,
        token: str,
        owner_user_id: str,
        conversation_id: str,
        file_path: str,
        mime_type: str | None,
        filename: str | None,
        expires_at: datetime,
    ) -> None:
        async with self._relational_session() as session:
            await session.execute(
                self._schema_sql(
                    "INSERT INTO mugen.web_media_token "
                    "("
                    "token, owner_user_id, conversation_id, file_path, mime_type, "
                    "filename, expires_at, created_at, updated_at"
                    ") "
                    "VALUES ("
                    ":token, :owner_user_id, :conversation_id, :file_path, "
                    ":mime_type, :filename, :expires_at, now(), now()"
                    ")"
                ),
                {
                    "token": token,
                    "owner_user_id": owner_user_id,
                    "conversation_id": conversation_id,
                    "file_path": file_path,
                    "mime_type": mime_type,
                    "filename": filename,
                    "expires_at": expires_at,
                },
            )

    async def get_media_token(self, *, token: str) -> dict[str, Any] | None:
        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT token, owner_user_id, file_path, mime_type, filename, "
                    "expires_at "
                    "FROM mugen.web_media_token "
                    "WHERE token = :token"
                ),
                {"token": token},
            )
            row = result.mappings().one_or_none()
            if row is None:
                return None
            return dict(row)

    async def recover_stale_processing_jobs(self, *, now_ts: datetime) -> int:
        async with self._relational_session() as session:
            recovered_result = await session.execute(
                self._schema_sql(
                    "UPDATE mugen.web_queue_job "
                    "SET status = 'pending', lease_expires_at = NULL, updated_at = now() "
                    "WHERE status = 'processing' "
                    "AND (lease_expires_at IS NULL OR lease_expires_at <= :now_ts)"
                ),
                {"now_ts": now_ts},
            )
        return int(getattr(recovered_result, "rowcount", 0) or 0)

    @staticmethod
    def _can_apply_terminal_queue_transition(
        *,
        current_status: Any,
        next_status: str,
    ) -> bool:
        if next_status not in {"done", "failed"}:
            return True

        normalized_current_status = str(current_status or "").strip().lower()
        return normalized_current_status == "processing"

    def _apply_queue_job_status_transition(
        self,
        *,
        job: dict[str, Any],
        status: str,
        error: str | None,
        now_iso: str,
    ) -> dict[str, Any]:
        if status == "done":
            return self._queue_job_lifecycle_use_case.complete(
                job=job,
                now_iso=now_iso,
            )
        if status == "failed":
            return self._queue_job_lifecycle_use_case.fail(
                job=job,
                now_iso=now_iso,
                error=str(error or ""),
            )

        next_job = dict(job)
        next_job["status"] = status
        next_job["lease_expires_at"] = None
        next_job["updated_at"] = now_iso
        next_job["error"] = error
        return next_job

    async def mark_job_status(
        self,
        *,
        job_id: str,
        status: str,
        error: str | None,
        expected_attempt: int | None,
        now_iso: str,
        event_log_version: int,
    ) -> int:
        _ = event_log_version
        normalized_status = str(status).strip().lower()
        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT job_id, conversation_id, sender, message_type, payload, "
                    "status, attempts, created_at, updated_at, lease_expires_at, "
                    "error_message, completed_at, client_message_id "
                    "FROM mugen.web_queue_job "
                    "WHERE job_id = :job_id"
                ),
                {"job_id": job_id},
            )
            row = result.mappings().one_or_none()
            if row is None:
                return 0

            current_job = self._queue_job_record_to_payload(row)
            if not self._can_apply_terminal_queue_transition(
                current_status=current_job.get("status"),
                next_status=normalized_status,
            ):
                self._logging_gateway.warning(
                    "Skipping queue status transition that violates lifecycle invariant "
                    f"job_id={job_id} current_status={current_job.get('status')!r} "
                    f"next_status={normalized_status!r}."
                )
                return 0

            transitioned = self._apply_queue_job_status_transition(
                job=current_job,
                status=normalized_status,
                error=error,
                now_iso=now_iso,
            )
            update_sql = (
                "UPDATE mugen.web_queue_job "
                "SET status = :status, "
                "lease_expires_at = NULL, "
                "updated_at = :updated_at, "
                "error_message = :error_message, "
                "completed_at = :completed_at "
            )
            update_params = {
                "status": str(transitioned.get("status", normalized_status)),
                "updated_at": (
                    self._iso_to_utc_datetime(transitioned.get("updated_at"))
                    or self._to_utc_datetime(datetime.now(timezone.utc).timestamp())
                ),
                "error_message": (
                    str(transitioned.get("error"))
                    if transitioned.get("error") not in [None, ""]
                    else None
                ),
                "completed_at": self._iso_to_utc_datetime(transitioned.get("completed_at")),
                "job_id": job_id,
            }
            if normalized_status in {"done", "failed"}:
                update_sql += (
                    "WHERE job_id = :job_id "
                    "AND status = :current_status "
                    "AND attempts = :expected_attempt"
                )
                update_params["current_status"] = "processing"
                update_params["expected_attempt"] = (
                    int(expected_attempt)
                    if expected_attempt is not None
                    else int(current_job.get("attempts") or 0)
                )
            else:
                update_sql += "WHERE job_id = :job_id"

            update_result = await session.execute(
                self._schema_sql(update_sql),
                update_params,
            )
            rowcount = int(getattr(update_result, "rowcount", 0) or 0)
            if normalized_status in {"done", "failed"} and rowcount == 0:
                self._logging_gateway.warning(
                    "Skipped queue terminal transition due to relational "
                    f"precondition mismatch job_id={job_id} "
                    f"next_status={normalized_status!r}."
                )
            return rowcount

    async def read_queue_state(self, *, queue_state_version: int) -> dict[str, Any]:
        async with self._relational_session() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT job_id, conversation_id, sender, message_type, payload, "
                    "status, attempts, created_at, updated_at, lease_expires_at, "
                    "error_message, completed_at, client_message_id "
                    "FROM mugen.web_queue_job "
                    "ORDER BY created_at ASC"
                )
            )
            jobs = [self._queue_job_record_to_payload(row) for row in result.mappings().all()]
        return {
            "version": queue_state_version,
            "jobs": jobs,
        }

    async def write_queue_state(self, *, queue_state: dict[str, Any]) -> None:
        jobs = queue_state.get("jobs", []) if isinstance(queue_state, dict) else []
        if not isinstance(jobs, list):
            jobs = []

        now_epoch = datetime.now(timezone.utc).timestamp()
        async with self._relational_session() as session:
            await session.execute(self._schema_sql("DELETE FROM mugen.web_queue_job"))
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                payload = {
                    "text": job.get("text"),
                    "metadata": (
                        dict(job.get("metadata"))
                        if isinstance(job.get("metadata"), dict)
                        else {}
                    ),
                    "file_path": job.get("file_path"),
                    "mime_type": job.get("mime_type"),
                    "original_filename": job.get("original_filename"),
                }
                await session.execute(
                    self._schema_sql(
                        "INSERT INTO mugen.web_queue_job "
                        "("
                        "job_id, conversation_id, sender, message_type, payload, "
                        "status, attempts, lease_expires_at, error_message, "
                        "completed_at, client_message_id, created_at, updated_at"
                        ") "
                        "VALUES ("
                        ":job_id, :conversation_id, :sender, :message_type, "
                        "CAST(:payload AS jsonb), :status, :attempts, "
                        ":lease_expires_at, :error_message, :completed_at, "
                        ":client_message_id, :created_at, :updated_at"
                        ")"
                    ),
                    {
                        "job_id": str(job.get("id", "")),
                        "conversation_id": str(job.get("conversation_id", "")),
                        "sender": str(job.get("sender", "")),
                        "message_type": str(job.get("message_type", "")),
                        "payload": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                        "status": str(job.get("status", "pending")),
                        "attempts": int(job.get("attempts") or 0),
                        "lease_expires_at": (
                            self._to_utc_datetime(float(job.get("lease_expires_at")))
                            if self._coerce_float(job.get("lease_expires_at")) is not None
                            else None
                        ),
                        "error_message": (
                            str(job.get("error")) if job.get("error") not in [None, ""] else None
                        ),
                        "completed_at": self._iso_to_utc_datetime(job.get("completed_at")),
                        "client_message_id": (
                            str(job.get("client_message_id"))
                            if job.get("client_message_id") not in [None, ""]
                            else None
                        ),
                        "created_at": self._iso_to_utc_datetime(job.get("created_at"))
                        or self._to_utc_datetime(now_epoch),
                        "updated_at": self._iso_to_utc_datetime(job.get("updated_at"))
                        or self._to_utc_datetime(now_epoch),
                    },
                )

    async def read_event_log(
        self,
        *,
        conversation_id: str,
        event_log_version: int,
        replay_max_events: int,
        new_stream_generation: str,
    ) -> dict[str, Any]:
        async with self._relational_session() as session:
            state_result = await session.execute(
                self._schema_sql(
                    "SELECT stream_generation, stream_version, next_event_id "
                    "FROM mugen.web_conversation_state "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            state = state_result.mappings().one_or_none()
            if state is None:
                return self._new_event_log_state(event_log_version)

            raw_version = state.get("stream_version")
            try:
                parsed_version = int(raw_version)
            except (TypeError, ValueError):
                parsed_version = None

            if parsed_version != event_log_version:
                self._logging_gateway.warning(
                    "Web event log version mismatch; resetting conversation stream log "
                    f"(conversation_id={conversation_id} stored_version={raw_version!r} "
                    f"expected_version={event_log_version})."
                )
                return self._new_event_log_state(event_log_version)

            events_result = await session.execute(
                self._schema_sql(
                    "SELECT event_id, event_type, payload, created_at, stream_generation, "
                    "stream_version "
                    "FROM mugen.web_conversation_event "
                    "WHERE conversation_id = :conversation_id "
                    "ORDER BY event_id DESC "
                    "LIMIT :event_limit"
                ),
                {
                    "conversation_id": conversation_id,
                    "event_limit": replay_max_events,
                },
            )
            rows = list(reversed(events_result.mappings().all()))
            events: list[dict[str, Any]] = []
            for row in rows:
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    payload = {}
                events.append(
                    {
                        "id": str(row.get("event_id")),
                        "event": str(row.get("event_type")),
                        "data": payload,
                        "created_at": self._datetime_to_iso(row.get("created_at")),
                        "stream_generation": self._normalize_stream_generation(
                            row.get("stream_generation"),
                            fallback=self._normalize_stream_generation(
                                state.get("stream_generation"),
                                fallback=new_stream_generation,
                            ),
                        ),
                        "stream_version": int(
                            row.get("stream_version") or event_log_version
                        ),
                    }
                )

            next_event_id = state.get("next_event_id")
            try:
                next_id = int(next_event_id)
            except (TypeError, ValueError):
                next_id = 1
            if next_id <= 0:
                next_id = 1

            return {
                "version": event_log_version,
                "generation": self._normalize_stream_generation(
                    state.get("stream_generation"),
                    fallback=new_stream_generation,
                ),
                "next_event_id": next_id,
                "events": events,
            }

    async def write_event_log(
        self,
        *,
        conversation_id: str,
        payload: dict[str, Any],
        event_log_version: int,
        now_epoch: float,
        new_stream_generation: str,
    ) -> None:
        generation = self._normalize_stream_generation(
            payload.get("generation"),
            fallback=new_stream_generation,
        )
        try:
            next_event_id = int(payload.get("next_event_id"))
        except (TypeError, ValueError):
            next_event_id = 1
        if next_event_id <= 0:
            next_event_id = 1

        events = payload.get("events", [])
        if not isinstance(events, list):
            events = []

        async with self._relational_session() as session:
            owner_result = await session.execute(
                self._schema_sql(
                    "SELECT owner_user_id "
                    "FROM mugen.web_conversation_state "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            owner_row = owner_result.mappings().one_or_none()
            owner_user_id = owner_row.get("owner_user_id") if owner_row is not None else "system"

            await session.execute(
                self._schema_sql(
                    "INSERT INTO mugen.web_conversation_state "
                    "("
                    "conversation_id, owner_user_id, stream_generation, "
                    "stream_version, next_event_id, created_at, updated_at"
                    ") "
                    "VALUES ("
                    ":conversation_id, :owner_user_id, :stream_generation, "
                    ":stream_version, :next_event_id, now(), now()"
                    ") "
                    "ON CONFLICT (conversation_id) DO UPDATE "
                    "SET stream_generation = EXCLUDED.stream_generation, "
                    "stream_version = EXCLUDED.stream_version, "
                    "next_event_id = EXCLUDED.next_event_id, "
                    "updated_at = now()"
                ),
                {
                    "conversation_id": conversation_id,
                    "owner_user_id": owner_user_id,
                    "stream_generation": generation,
                    "stream_version": event_log_version,
                    "next_event_id": next_event_id,
                },
            )

            await session.execute(
                self._schema_sql(
                    "DELETE FROM mugen.web_conversation_event "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )

            for event in events:
                if not isinstance(event, dict):
                    continue
                parsed_event_id = self._parse_event_id(event.get("id"))
                if parsed_event_id is None:
                    continue
                event_payload = event.get("data")
                if not isinstance(event_payload, dict):
                    event_payload = {}
                await session.execute(
                    self._schema_sql(
                        "INSERT INTO mugen.web_conversation_event "
                        "("
                        "conversation_id, event_id, event_type, payload, "
                        "stream_generation, stream_version, created_at, updated_at"
                        ") "
                        "VALUES ("
                        ":conversation_id, :event_id, :event_type, CAST(:payload AS jsonb), "
                        ":stream_generation, :stream_version, :created_at, now()"
                        ") "
                        "ON CONFLICT (conversation_id, event_id) DO UPDATE "
                        "SET event_type = EXCLUDED.event_type, "
                        "payload = EXCLUDED.payload, "
                        "stream_generation = EXCLUDED.stream_generation, "
                        "stream_version = EXCLUDED.stream_version, "
                        "updated_at = now()"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "event_id": parsed_event_id,
                        "event_type": str(event.get("event", "system")),
                        "payload": json.dumps(
                            event_payload, ensure_ascii=True, separators=(",", ":")
                        ),
                        "stream_generation": self._normalize_stream_generation(
                            event.get("stream_generation"),
                            fallback=generation,
                        ),
                        "stream_version": int(
                            event.get("stream_version") or event_log_version
                        ),
                        "created_at": self._iso_to_utc_datetime(event.get("created_at"))
                        or self._to_utc_datetime(now_epoch),
                    },
                )
