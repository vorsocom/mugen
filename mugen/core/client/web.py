"""Provides an implementation of IWebClient."""

__all__ = ["DefaultWebClient"]

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import copy
from datetime import datetime, timezone
import fnmatch
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import uuid

from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.media import IMediaStorageGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.gateway.storage.web_runtime.sql import text as web_sql_text
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService
from mugen.core.domain.use_case.enqueue_web_message import BuildQueuedMessageJobUseCase
from mugen.core.domain.use_case.normalize_composed_message import (
    NormalizeComposedMessageUseCase,
)
from mugen.core.domain.use_case.queue_job_lifecycle import QueueJobLifecycleUseCase
from mugen.core.gateway.storage.media import (
    FilesystemMediaStorageGateway,
    ObjectMediaStorageGateway,
)
from mugen.core.utility.processing_signal import (
    PROCESSING_SIGNAL_THINKING,
    PROCESSING_STATE_START,
    PROCESSING_STATE_STOP,
    build_thinking_signal_payload,
)


# pylint: disable=too-many-instance-attributes
class DefaultWebClient(IWebClient):
    """An implementation of IWebClient."""

    _accepted_message_types = {
        "text",
        "audio",
        "video",
        "file",
        "image",
        "composed",
    }
    _accepted_response_types = {
        "text",
        "audio",
        "video",
        "file",
        "image",
    }
    _required_correlation_event_types = {
        "ack",
        "message",
        "system",
        "error",
        PROCESSING_SIGNAL_THINKING,
    }

    _queue_state_version = 1

    _event_log_version = 3

    _stream_reset_signal = "stream_reset"

    _default_sse_keepalive_seconds: float = 15.0
    _default_sse_replay_max_events: int = 200
    _default_sse_enqueue_timeout_seconds: float = 0.5
    _default_queue_poll_interval_seconds: float = 0.25
    _default_queue_processing_lease_seconds: float = 30.0
    _default_queue_max_pending_jobs: int = 2000
    _default_media_backend: str = "filesystem"
    _default_media_storage_path: str = "data/web_media"
    _default_media_object_cache_path: str = "data/web_media_object_cache"
    _default_media_max_upload_bytes: int = 20 * 1024 * 1024
    _default_media_max_attachments_per_message: int = 10
    _default_media_allowed_mimetypes: list[str] = [
        "audio/*",
        "video/*",
        "image/*",
        "application/*",
    ]
    _default_media_download_token_ttl_seconds: int = 900
    _default_media_retention_seconds: int = 86400

    _sse_queue_size: int = 128

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        config: SimpleNamespace = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        relational_storage_gateway: IRelationalStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        self._config = config
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._relational_storage_gateway = relational_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

        self._storage_lock = asyncio.Lock()
        self._subscriber_lock = asyncio.Lock()
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

        self._worker_task: asyncio.Task | None = None
        self._worker_stop = asyncio.Event()
        self._worker_failure: BaseException | None = None
        self._enqueue_job_use_case = BuildQueuedMessageJobUseCase.with_defaults()
        self._queue_job_lifecycle_use_case = QueueJobLifecycleUseCase()

        self._sse_keepalive_seconds = self._resolve_float_config(
            ("web", "sse", "keepalive_seconds"),
            self._default_sse_keepalive_seconds,
            minimum=1.0,
        )
        self._sse_replay_max_events = self._resolve_int_config(
            ("web", "sse", "replay_max_events"),
            self._default_sse_replay_max_events,
            minimum=1,
        )
        self._sse_enqueue_timeout_seconds = self._resolve_float_config(
            ("web", "sse", "enqueue_timeout_seconds"),
            self._default_sse_enqueue_timeout_seconds,
            minimum=0.01,
        )
        self._sse_disconnect_sentinel = object()
        self._queue_poll_interval_seconds = self._resolve_float_config(
            ("web", "queue", "poll_interval_seconds"),
            self._default_queue_poll_interval_seconds,
            minimum=0.05,
        )
        self._queue_processing_lease_seconds = self._resolve_float_config(
            ("web", "queue", "processing_lease_seconds"),
            self._default_queue_processing_lease_seconds,
            minimum=1.0,
        )
        self._queue_processing_lease_heartbeat_seconds = (
            self._derive_queue_lease_heartbeat_seconds(
                self._queue_processing_lease_seconds
            )
        )
        self._queue_max_pending_jobs = self._resolve_int_config(
            ("web", "queue", "max_pending_jobs"),
            self._default_queue_max_pending_jobs,
            minimum=1,
        )

        storage_path = self._resolve_str_config(
            ("web", "media", "storage", "path"),
            self._default_media_storage_path,
        )
        self._media_storage_path = self._resolve_storage_path(storage_path)
        self._media_backend = self._resolve_str_config(
            ("web", "media", "backend"),
            self._default_media_backend,
        ).strip().lower()
        self._media_storage_gateway = self._build_media_storage_gateway()

        self._media_max_upload_bytes = self._resolve_int_config(
            ("web", "media", "max_upload_bytes"),
            self._default_media_max_upload_bytes,
            minimum=1,
        )
        self._media_max_attachments_per_message = self._resolve_int_config(
            ("web", "media", "max_attachments_per_message"),
            self._default_media_max_attachments_per_message,
            minimum=1,
        )
        self._media_allowed_mimetypes = self._resolve_allowed_mimetypes()
        self._media_download_token_ttl_seconds = self._resolve_int_config(
            ("web", "media", "download_token_ttl_seconds"),
            self._default_media_download_token_ttl_seconds,
            minimum=1,
        )
        self._media_retention_seconds = self._resolve_int_config(
            ("web", "media", "retention_seconds"),
            self._default_media_retention_seconds,
            minimum=1,
        )

    async def init(self) -> None:
        """Start the background worker loop."""
        self._logging_gateway.debug("DefaultWebClient.init")
        self._ensure_media_directory()
        await self._media_storage_gateway.init()

        async with self._storage_lock:
            await self._recover_stale_processing_jobs_unlocked()

        if self._worker_task is not None and not self._worker_task.done():
            return

        self._worker_stop.clear()
        self._worker_failure = None
        self._worker_task = asyncio.create_task(
            self._worker_loop(),
            name="mugen.web.worker",
        )
        self._worker_task.add_done_callback(self._on_worker_task_done)

    def _on_worker_task_done(self, task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return

        if exc is None:
            return

        self._worker_failure = exc
        self._logging_gateway.error(
            "DefaultWebClient worker crashed "
            f"error_type={type(exc).__name__} error={exc}"
        )

    async def wait_until_stopped(self) -> None:
        """Wait for worker completion and surface worker failures."""
        task = self._worker_task
        if task is None:
            raise RuntimeError("Web client worker is not running.")
        await task

    async def close(self) -> None:
        """Stop the worker loop and release in-memory subscribers."""
        self._logging_gateway.debug("DefaultWebClient.close")
        self._worker_stop.set()

        task = self._worker_task
        self._worker_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                ...

        async with self._subscriber_lock:
            self._subscribers.clear()

        try:
            await self._media_storage_gateway.close()
        except Exception:  # pylint: disable=broad-exception-caught
            ...

    def _raw_relational_session_provider(self):
        if self._relational_storage_gateway is None:
            return None

        raw_session = getattr(self._relational_storage_gateway, "raw_session", None)
        if callable(raw_session):
            return raw_session

        raise RuntimeError(
            "Relational web storage is configured but "
            "relational_storage_gateway.raw_session is unavailable."
        )

    def _using_relational_web_storage(self) -> bool:
        return self._relational_storage_gateway is not None

    @asynccontextmanager
    async def _relational_session(self):
        raw_session = self._raw_relational_session_provider()
        if raw_session is None:
            raise RuntimeError("Relational web storage is unavailable.")
        async with raw_session() as session:
            yield session

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

    def _queue_job_record_to_payload(self, row: Any) -> dict[str, Any]:
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
            "created_at": self._datetime_to_iso(getter("created_at")),
            "updated_at": self._datetime_to_iso(getter("updated_at")),
            "lease_expires_at": self._datetime_to_epoch(getter("lease_expires_at")),
            "error": getter("error_message"),
            "completed_at": self._datetime_to_iso(getter("completed_at")),
        }

    async def enqueue_message(  # pylint: disable=too-many-arguments
        self,
        *,
        auth_user: str,
        conversation_id: str,
        message_type: str,
        text: str | None = None,
        metadata: dict[str, Any] | None = None,
        file_path: str | None = None,
        mime_type: str | None = None,
        original_filename: str | None = None,
        client_message_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist and enqueue a user message for async processing."""
        normalized_type = self._normalize_message_type(message_type)
        payload_metadata = metadata
        if normalized_type == "composed":
            payload_metadata = self._normalize_composed_metadata(metadata)
            payload_metadata = await self._persist_composed_media_references(
                payload_metadata
            )

        persisted_file_path = file_path
        if normalized_type not in {"text", "composed"}:
            persisted_file_path = await self._persist_media_reference(
                file_path=file_path,
                filename_hint=original_filename,
            )

        now_iso = self._utc_now_iso()
        job_id = uuid.uuid4().hex
        normalized_client_message_id = self._normalize_client_message_id(
            client_message_id=client_message_id,
            job_id=job_id,
            conversation_id=conversation_id,
            source="enqueue_message",
            event_type="ack",
        )
        job_entity = self._enqueue_job_use_case.handle(
            job_id=job_id,
            auth_user=auth_user,
            conversation_id=conversation_id,
            message_type=normalized_type,
            text=text,
            metadata=payload_metadata,
            file_path=persisted_file_path,
            mime_type=mime_type,
            original_filename=original_filename,
            client_message_id=normalized_client_message_id,
        )
        job = job_entity.as_pending_record(now_iso=now_iso)
        conversation = job_entity.conversation_id
        auth_user_id = job_entity.sender

        async with self._storage_lock:
            await self._ensure_conversation_owner_unlocked(
                conversation_id=conversation,
                auth_user=auth_user_id,
                create_if_missing=True,
            )

            async with self._relational_session() as session:
                pending_result = await session.execute(
                    web_sql_text(
                        "SELECT count(*) "
                        "FROM mugen.web_queue_job "
                        "WHERE status = 'pending'"
                    )
                )
                pending_count = int(pending_result.scalar() or 0)
                if pending_count >= self._queue_max_pending_jobs:
                    raise OverflowError("queue is full")

                payload = {
                    "text": job["text"],
                    "metadata": job["metadata"],
                    "file_path": job["file_path"],
                    "mime_type": job["mime_type"],
                    "original_filename": job["original_filename"],
                }
                await session.execute(
                    web_sql_text(
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
                        "conversation_id": conversation,
                        "sender": auth_user_id,
                        "message_type": job["message_type"],
                        "payload": json.dumps(
                            payload, ensure_ascii=True, separators=(",", ":")
                        ),
                        "client_message_id": normalized_client_message_id,
                    },
                )

        ack_payload = {
            "job_id": job_id,
            "conversation_id": conversation,
            "client_message_id": normalized_client_message_id,
            "status": "accepted",
            "accepted_at": now_iso,
        }
        await self._append_event(
            conversation_id=conversation,
            event_type="ack",
            data=ack_payload,
        )

        return {
            "job_id": job_id,
            "conversation_id": conversation,
            "accepted_at": now_iso,
        }

    async def stream_events(
        self,
        *,
        auth_user: str,
        conversation_id: str,
        last_event_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream replay and live events as SSE payload chunks."""
        auth_user_id = self._require_non_empty(auth_user, "auth_user")
        conversation = self._require_non_empty(conversation_id, "conversation_id")

        async with self._storage_lock:
            await self._ensure_conversation_owner_unlocked(
                conversation_id=conversation,
                auth_user=auth_user_id,
                create_if_missing=False,
            )
            log = await self._read_event_log_unlocked(conversation)
            stream_generation = self._normalize_stream_generation(
                log.get("generation"),
                fallback=self._new_stream_generation(),
            )
            max_event_id = max(int(log["next_event_id"]) - 1, 0)

            cursor = self._resolve_stream_cursor(
                conversation_id=conversation,
                incoming_last_event_id=last_event_id,
                stream_generation=stream_generation,
                max_event_id=max_event_id,
            )
            replay_events = [
                event
                for event in list(log["events"])
                if (
                    self._parse_event_id(event.get("id")) is None
                    or (self._parse_event_id(event.get("id")) or 0)
                    > int(cursor["effective_last_event_id"])
                )
            ]

        subscriber_queue: asyncio.Queue = asyncio.Queue(maxsize=self._sse_queue_size)
        await self._register_subscriber(conversation, subscriber_queue)

        async def _event_stream() -> AsyncIterator[str]:
            highest_event_id = int(cursor["effective_last_event_id"])
            active_generation = stream_generation
            try:
                reset_event = cursor.get("reset_event")
                if isinstance(reset_event, dict):
                    yield self._format_sse_event(reset_event)

                for event in replay_events:
                    event_generation = self._normalize_stream_generation(
                        event.get("stream_generation"),
                        fallback=active_generation,
                    )
                    if event_generation != active_generation:
                        self._log_sse_diagnostic(
                            conversation_id=conversation,
                            incoming_event_id=event.get("id"),
                            last_event_id=highest_event_id,
                            reason="replay_generation_changed",
                        )
                        active_generation = event_generation
                        highest_event_id = 0
                        yield self._format_sse_event(
                            self._build_stream_reset_event(
                                conversation_id=conversation,
                                reason="replay_generation_changed",
                                incoming_last_event_id=last_event_id,
                                incoming_event_id=self._parse_event_id(event.get("id")),
                                stream_generation=active_generation,
                            )
                        )

                    event_id = self._parse_event_id(event.get("id"))
                    if event_id is not None and event_id <= highest_event_id:
                        self._log_sse_diagnostic(
                            conversation_id=conversation,
                            incoming_event_id=event.get("id"),
                            last_event_id=highest_event_id,
                            reason="replay_event_id_not_greater_than_cursor",
                        )
                        continue
                    if event_id is not None:
                        highest_event_id = event_id
                    yield self._format_sse_event(
                        self._build_stream_sse_event(
                            event=event,
                            stream_generation=event_generation,
                        )
                    )

                while True:
                    try:
                        event = await asyncio.wait_for(
                            subscriber_queue.get(),
                            timeout=self._sse_keepalive_seconds,
                        )
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue

                    if event is self._sse_disconnect_sentinel:
                        self._log_sse_diagnostic(
                            conversation_id=conversation,
                            incoming_event_id=None,
                            last_event_id=highest_event_id,
                            reason="subscriber_disconnected_for_backpressure",
                            warning=True,
                        )
                        break

                    if not isinstance(event, dict):
                        self._log_sse_diagnostic(
                            conversation_id=conversation,
                            incoming_event_id=event,
                            last_event_id=highest_event_id,
                            reason="live_event_invalid_payload",
                        )
                        continue

                    event_generation = self._normalize_stream_generation(
                        event.get("stream_generation"),
                        fallback=active_generation,
                    )
                    if event_generation != active_generation:
                        self._log_sse_diagnostic(
                            conversation_id=conversation,
                            incoming_event_id=event.get("id"),
                            last_event_id=highest_event_id,
                            reason="live_generation_changed",
                        )
                        active_generation = event_generation
                        highest_event_id = 0
                        yield self._format_sse_event(
                            self._build_stream_reset_event(
                                conversation_id=conversation,
                                reason="live_generation_changed",
                                incoming_last_event_id=last_event_id,
                                incoming_event_id=self._parse_event_id(event.get("id")),
                                stream_generation=active_generation,
                            )
                        )

                    event_id = self._parse_event_id(event.get("id"))
                    if event_id is not None and event_id <= highest_event_id:
                        self._log_sse_diagnostic(
                            conversation_id=conversation,
                            incoming_event_id=event.get("id"),
                            last_event_id=highest_event_id,
                            reason="live_event_id_not_greater_than_cursor",
                        )
                        continue
                    if event_id is not None:
                        highest_event_id = event_id
                    yield self._format_sse_event(
                        self._build_stream_sse_event(
                            event=event,
                            stream_generation=event_generation,
                        )
                    )
            finally:
                await self._unregister_subscriber(conversation, subscriber_queue)

        return _event_stream()

    async def resolve_media_download(
        self,
        *,
        auth_user: str,
        token: str,
    ) -> dict[str, Any] | None:
        """Resolve a media token to an authorized media file payload."""
        auth_user_id = self._require_non_empty(auth_user, "auth_user")

        async with self._storage_lock:
            async with self._relational_session() as session:
                result = await session.execute(
                    web_sql_text(
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

                expires_at = self._datetime_to_epoch(row.get("expires_at"))
                if expires_at is None or expires_at <= self._epoch_now():
                    await session.execute(
                        web_sql_text(
                            "DELETE FROM mugen.web_media_token "
                            "WHERE token = :token"
                        ),
                        {"token": token},
                    )
                    return None

                owner_user_id = row.get("owner_user_id")
                if owner_user_id != auth_user_id:
                    return None

                media_ref = row.get("file_path")
                if not isinstance(media_ref, str) or media_ref == "":
                    return None

                resolved_path = await self._media_storage_gateway.materialize(media_ref)
                if resolved_path is None:
                    await session.execute(
                        web_sql_text(
                            "DELETE FROM mugen.web_media_token "
                            "WHERE token = :token"
                        ),
                        {"token": token},
                    )
                    return None

                return {
                    "file_path": resolved_path,
                    "mime_type": row.get("mime_type"),
                    "filename": row.get("filename"),
                }

    @property
    def media_max_upload_bytes(self) -> int:
        """Expose configured upload size limit for API validators."""
        return self._media_max_upload_bytes

    @property
    def media_allowed_mimetypes(self) -> list[str]:
        """Expose configured upload mime allow-list for API validators."""
        return list(self._media_allowed_mimetypes)

    @property
    def media_max_attachments_per_message(self) -> int:
        """Expose max structured upload count for API validators."""
        return self._media_max_attachments_per_message

    def mimetype_allowed(self, mime_type: str | None) -> bool:
        """Validate mime type against configured allow-list."""
        if not isinstance(mime_type, str) or mime_type == "":
            return False

        normalized = mime_type.strip().lower()
        for allowed in self._media_allowed_mimetypes:
            if fnmatch.fnmatch(normalized, allowed):
                return True

        return False

    async def _worker_loop(self) -> None:
        maintenance_tick = 0
        while not self._worker_stop.is_set():
            claimed = await self._claim_next_job()
            if claimed is None:
                await self._sleep_until_poll()
            else:
                await self._process_claimed_job(claimed)

            maintenance_tick += 1
            if maintenance_tick % 20 == 0:
                await self._cleanup_media_tokens_and_files()

    async def _sleep_until_poll(self) -> None:
        try:
            await asyncio.wait_for(
                self._worker_stop.wait(),
                timeout=self._queue_poll_interval_seconds,
            )
        except asyncio.TimeoutError:
            ...

    async def _claim_next_job(self) -> dict[str, Any] | None:
        now_epoch = self._epoch_now()
        now_iso = self._utc_now_iso()

        async with self._storage_lock:
            async with self._relational_session() as session:
                recovered_result = await session.execute(
                    web_sql_text(
                        "UPDATE mugen.web_queue_job "
                        "SET status = 'pending', lease_expires_at = NULL, updated_at = now() "
                        "WHERE status = 'processing' "
                        "AND (lease_expires_at IS NULL OR lease_expires_at <= now())"
                    )
                )
                recovered_count = int(getattr(recovered_result, "rowcount", 0) or 0)
                if recovered_count > 0:
                    self._logging_gateway.warning(
                        "Web worker lease recovery reset stale jobs "
                        f"(count={recovered_count})."
                    )

                selected = await session.execute(
                    web_sql_text(
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
                    return None

                selected_job = self._queue_job_record_to_payload(selected_row)
                claimed_view = self._queue_job_lifecycle_use_case.claim(
                    job=selected_job,
                    now_iso=now_iso,
                    lease_expires_at=(now_epoch + self._queue_processing_lease_seconds),
                )
                updated = await session.execute(
                    web_sql_text(
                        "UPDATE mugen.web_queue_job "
                        "SET status = CAST(:status AS mugen.citext), "
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
                            self._to_utc_datetime(
                                float(claimed_view.get("lease_expires_at"))
                            )
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
                    return None
                return self._queue_job_record_to_payload(row)

    @staticmethod
    def _derive_queue_lease_heartbeat_seconds(lease_seconds: float) -> float:
        try:
            normalized_lease_seconds = float(lease_seconds)
        except (TypeError, ValueError):
            normalized_lease_seconds = 1.0
        return max(1.0, min(normalized_lease_seconds / 3.0, 10.0))

    async def _processing_owner_matches(
        self,
        *,
        job_id: str,
        expected_attempt: int,
    ) -> bool:
        async with self._storage_lock:
            async with self._relational_session() as session:
                result = await session.execute(
                    web_sql_text(
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

    async def _renew_processing_lease(
        self,
        *,
        job_id: str,
        expected_attempt: int | None = None,
    ) -> bool:
        now_epoch = self._epoch_now()
        now_iso = self._utc_now_iso()
        next_lease_expires_at = now_epoch + self._queue_processing_lease_seconds
        async with self._storage_lock:
            async with self._relational_session() as session:
                result = await session.execute(
                    web_sql_text(
                        "UPDATE mugen.web_queue_job "
                        "SET lease_expires_at = :lease_expires_at, "
                        "updated_at = :updated_at "
                        "WHERE job_id = :job_id "
                        "AND status = CAST(:current_status AS mugen.citext)"
                        "AND (:expected_attempt IS NULL OR attempts = :expected_attempt)"
                    ),
                    {
                        "lease_expires_at": self._to_utc_datetime(next_lease_expires_at),
                        "updated_at": (
                            self._iso_to_utc_datetime(now_iso)
                            or self._to_utc_datetime(now_epoch)
                        ),
                        "job_id": job_id,
                        "current_status": "processing",
                        "expected_attempt": (
                            int(expected_attempt)
                            if expected_attempt is not None
                            else None
                        ),
                    },
                )
            return int(getattr(result, "rowcount", 0) or 0) > 0

    async def _run_processing_lease_heartbeat(
        self,
        *,
        job_id: str,
        stop_event: asyncio.Event,
        expected_attempt: int | None = None,
    ) -> str | None:
        while True:
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._queue_processing_lease_heartbeat_seconds,
                )
                return None
            except asyncio.TimeoutError:
                ...

            try:
                renewed = await self._renew_processing_lease(
                    job_id=job_id,
                    expected_attempt=expected_attempt,
                )
            except Exception:  # pylint: disable=broad-exception-caught
                return "lease_renew_failed"

            if renewed is not True:
                return "lease_lost"

    async def _process_claimed_job(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("id"))
        conversation_id = str(job.get("conversation_id"))
        sender = str(job.get("sender"))
        message_type = str(job.get("message_type", "")).strip().lower()
        client_message_id = job.get("client_message_id")
        expected_attempt = int(job.get("attempts") or 0)
        lease_heartbeat_stop = asyncio.Event()
        lease_heartbeat_task = asyncio.create_task(
            self._run_processing_lease_heartbeat(
                job_id=job_id,
                stop_event=lease_heartbeat_stop,
                expected_attempt=expected_attempt,
            ),
            name=f"mugen.web.lease_heartbeat.{job_id}",
        )
        ownership_lost = False

        def _lease_loss_reason() -> str | None:
            if lease_heartbeat_task.done() is not True:
                return None
            try:
                return lease_heartbeat_task.result()
            except asyncio.CancelledError:
                return None
            except Exception:  # pylint: disable=broad-exception-caught
                return "lease_renew_failed"

        async def _should_skip_side_effects(stage: str) -> bool:
            nonlocal ownership_lost
            reason = _lease_loss_reason()
            if reason is not None:
                ownership_lost = True
                self._logging_gateway.warning(
                    "Skipping web queue job side effects after lease loss "
                    f"(job_id={job_id} conversation_id={conversation_id} "
                    f"stage={stage} reason={reason})."
                )
                return True

            try:
                owns_job = await self._processing_owner_matches(
                    job_id=job_id,
                    expected_attempt=expected_attempt,
                )
            except Exception:  # pylint: disable=broad-exception-caught
                ownership_lost = True
                self._logging_gateway.warning(
                    "Skipping web queue job side effects after lease loss "
                    f"(job_id={job_id} conversation_id={conversation_id} "
                    f"stage={stage} reason=lease_renew_failed)."
                )
                return True

            if owns_job is True:
                return False

            ownership_lost = True
            self._logging_gateway.warning(
                "Skipping web queue job side effects after lease loss "
                f"(job_id={job_id} conversation_id={conversation_id} "
                f"stage={stage} reason=lease_lost)."
            )
            return True

        await self._emit_thinking_signal(
            conversation_id=conversation_id,
            job_id=job_id,
            client_message_id=client_message_id,
            sender=sender,
            state=PROCESSING_STATE_START,
        )

        try:
            responses = await self._dispatch_job_to_messaging(job)
            if await _should_skip_side_effects("post_dispatch"):
                return

            if not responses:
                reason = "none" if responses is None else "empty-list"
                self._logging_gateway.warning(
                    "Web client fallback 'No response generated.' emitted: "
                    "messaging service returned no responses "
                    f"(reason={reason} job_id={job_id} "
                    f"conversation_id={conversation_id} "
                    f"client_message_id={client_message_id} "
                    f"message_type={message_type})."
                )
                if await _should_skip_side_effects("emit_fallback_response"):
                    return
                await self._append_event(
                    conversation_id=conversation_id,
                    event_type="system",
                    data={
                        "job_id": job_id,
                        "conversation_id": conversation_id,
                        "client_message_id": client_message_id,
                        "message": "No response generated.",
                    },
                )
            else:
                for response_index, response in enumerate(responses):
                    if self._is_blank_text_response(response):
                        content_type = type(response.get("content")).__name__
                        self._logging_gateway.warning(
                            "Web client fallback 'No response generated.' emitted: "
                            "blank text response content "
                            f"(job_id={job_id} conversation_id={conversation_id} "
                            f"client_message_id={client_message_id} "
                            f"response_index={response_index} "
                            f"content_type={content_type})."
                    )

                    event = await self._response_to_event(
                        response=response,
                        sender=sender,
                        conversation_id=conversation_id,
                    )

                    if await _should_skip_side_effects(f"emit_response_{response_index}"):
                        return
                    await self._append_event(
                        conversation_id=conversation_id,
                        event_type=event["event_type"],
                        data={
                            "job_id": job_id,
                            "conversation_id": conversation_id,
                            "client_message_id": client_message_id,
                            **event["payload"],
                        },
                    )

            if await _should_skip_side_effects("mark_done"):
                return
            await self._mark_job_done(job_id, expected_attempt=expected_attempt)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if await _should_skip_side_effects("handle_exception"):
                return
            await self._append_event(
                conversation_id=conversation_id,
                event_type="error",
                data={
                    "job_id": job_id,
                    "conversation_id": conversation_id,
                    "client_message_id": client_message_id,
                    "error": str(exc),
                },
            )
            if await _should_skip_side_effects("mark_failed"):
                return
            await self._mark_job_failed(
                job_id,
                str(exc),
                expected_attempt=expected_attempt,
            )
        finally:
            lease_heartbeat_stop.set()
            try:
                await lease_heartbeat_task
            except asyncio.CancelledError:
                ...
            final_reason = _lease_loss_reason()
            if final_reason is not None and ownership_lost is not True:
                ownership_lost = True
                self._logging_gateway.warning(
                    "Skipping web queue job side effects after lease loss "
                    f"(job_id={job_id} conversation_id={conversation_id} "
                    f"stage=emit_processing_stop reason={final_reason})."
                )
            if ownership_lost is not True:
                await self._emit_thinking_signal(
                    conversation_id=conversation_id,
                    job_id=job_id,
                    client_message_id=client_message_id,
                    sender=sender,
                    state=PROCESSING_STATE_STOP,
                )

    @staticmethod
    def _is_blank_text_response(response: Any) -> bool:
        if not isinstance(response, dict):
            return False

        response_type = str(response.get("type", "")).strip().lower()
        if response_type != "text":
            return False

        content = response.get("content")
        text_content = "" if content is None else str(content)
        return text_content.strip() == ""

    async def _emit_thinking_signal(
        self,
        *,
        conversation_id: str,
        job_id: str,
        client_message_id: str | None,
        sender: str,
        state: str,
    ) -> None:
        payload = build_thinking_signal_payload(
            state=state,
            job_id=job_id,
            conversation_id=conversation_id,
            client_message_id=client_message_id,
            sender=sender,
        )
        try:
            await self._append_event(
                conversation_id=conversation_id,
                event_type=PROCESSING_SIGNAL_THINKING,
                data=payload,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Failed to emit web thinking signal "
                f"(conversation_id={conversation_id} job_id={job_id}): {exc}"
            )

    async def _dispatch_job_to_messaging(
        self, job: dict[str, Any]
    ) -> list[dict] | None:
        message_type = str(job.get("message_type", "")).strip().lower()

        platform = "web"
        room_id = str(job.get("conversation_id"))
        sender = str(job.get("sender"))

        if message_type == "text":
            return await self._messaging_service.handle_text_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=str(job.get("text", "")),
            )

        if message_type == "composed":
            normalized_metadata = self._normalize_composed_metadata(job.get("metadata"))
            composed_message_payload: dict[str, Any] = {
                **normalized_metadata,
                "client_message_id": job.get("client_message_id"),
            }
            return await self._messaging_service.handle_composed_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=composed_message_payload,
            )

        materialized_file_path = await self._materialize_media_reference(
            job.get("file_path")
        )
        if materialized_file_path is None:
            raise ValueError("Media file no longer exists.")

        message_payload = {
            "file_path": materialized_file_path,
            "mime_type": job.get("mime_type"),
            "filename": job.get("original_filename"),
            "metadata": job.get("metadata") or {},
            "client_message_id": job.get("client_message_id"),
        }

        if message_type == "audio":
            return await self._messaging_service.handle_audio_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message_payload,
            )

        if message_type == "video":
            return await self._messaging_service.handle_video_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message_payload,
            )

        if message_type == "file":
            return await self._messaging_service.handle_file_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message_payload,
            )

        if message_type == "image":
            return await self._messaging_service.handle_image_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message_payload,
            )

        raise ValueError(f"Unsupported message type: {message_type}.")

    async def _response_to_event(
        self,
        *,
        response: Any,
        sender: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        if not isinstance(response, dict):
            return {
                "event_type": "message",
                "payload": {
                    "message": {
                        "type": "text",
                        "content": str(response),
                    }
                },
            }

        response_type = str(response.get("type", "")).strip().lower()
        if response_type == "":
            return {
                "event_type": "error",
                "payload": {"error": "Unsupported response type: <missing>."},
            }

        if response_type not in self._accepted_response_types:
            return {
                "event_type": "error",
                "payload": {"error": f"Unsupported response type: {response_type}."},
            }

        content = response.get("content")
        if content in [None, ""]:
            file_payload = response.get("file")
            if isinstance(file_payload, dict):
                content = file_payload

        if response_type == "text":
            text_content = "" if content is None else str(content)
            if text_content.strip() == "":
                text_content = "No response generated."
            return {
                "event_type": "message",
                "payload": {
                    "message": {
                        "type": "text",
                        "content": text_content,
                    }
                },
            }

        media_payload = await self._build_media_payload(
            content=content,
            owner_user_id=sender,
            conversation_id=conversation_id,
            fallback_mime_type=response.get("mime_type"),
            fallback_filename=response.get("filename"),
        )

        if media_payload is None:
            return {
                "event_type": "error",
                "payload": {
                    "error": (
                        f"Unsupported media response payload for type={response_type}."
                    )
                },
            }

        return {
            "event_type": "message",
            "payload": {
                "message": {
                    "type": response_type,
                    "content": media_payload,
                }
            },
        }

    async def _build_media_payload(
        self,
        *,
        content: Any,
        owner_user_id: str,
        conversation_id: str,
        fallback_mime_type: Any = None,
        fallback_filename: Any = None,
    ) -> dict[str, Any] | None:
        if isinstance(content, dict):
            media_url = content.get("url")
            if isinstance(media_url, str) and media_url != "":
                return content

            file_payload = content.get("file")
            if isinstance(file_payload, dict):
                content_source = file_payload
            else:
                content_source = content

            file_path = (
                content_source.get("file_path")
                or content_source.get("path")
                or content_source.get("uri")
            )
            mime_type = (
                content_source.get("mime_type")
                or content_source.get("mimetype")
                or self._coerce_media_mime(content_source.get("type"))
                or fallback_mime_type
            )
            filename = (
                content_source.get("filename")
                or content_source.get("name")
                or fallback_filename
            )
            return await self._create_media_token_payload(
                file_path=file_path,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                mime_type=mime_type,
                filename=filename,
            )

        if isinstance(content, str) and content != "":
            return await self._create_media_token_payload(
                file_path=content,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                mime_type=fallback_mime_type,
                filename=fallback_filename,
            )

        return None

    @staticmethod
    def _coerce_media_mime(value: Any) -> str | None:
        if not isinstance(value, str):
            return None

        normalized = value.strip().lower()
        if normalized == "" or "/" not in normalized:
            return None

        return normalized

    async def _create_media_token_payload(
        self,
        *,
        file_path: Any,
        owner_user_id: str,
        conversation_id: str,
        mime_type: Any,
        filename: Any,
    ) -> dict[str, Any] | None:
        media_ref = await self._resolve_media_source_path(
            file_path=file_path,
            filename=filename,
        )
        if media_ref is None:
            return None

        token = uuid.uuid4().hex
        expires_at = self._epoch_now() + self._media_download_token_ttl_seconds
        normalized_mime_type = (
            str(mime_type).strip() if mime_type not in [None, ""] else None
        )
        normalized_filename = (
            str(filename).strip()
            if filename not in [None, ""]
            else os.path.basename(media_ref)
        )

        token_payload = {
            "owner_user_id": owner_user_id,
            "conversation_id": conversation_id,
            "file_path": media_ref,
            "media_ref": media_ref,
            "mime_type": normalized_mime_type,
            "filename": normalized_filename,
            "expires_at": expires_at,
        }

        async with self._storage_lock:
            async with self._relational_session() as session:
                await session.execute(
                    web_sql_text(
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
                        "file_path": media_ref,
                        "mime_type": normalized_mime_type,
                        "filename": normalized_filename,
                        "expires_at": self._to_utc_datetime(expires_at),
                    },
                )

        return {
            "url": f"/api/core/web/v1/media/{token}",
            "token": token,
            "mime_type": normalized_mime_type,
            "filename": normalized_filename,
            "expires_at": expires_at,
        }

    async def _resolve_media_source_path(
        self,
        *,
        file_path: Any,
        filename: Any,
    ) -> str | None:
        if isinstance(file_path, str) and file_path != "":
            if await self._media_storage_gateway.exists(file_path):
                return file_path
            normalized_path = os.path.abspath(file_path)
            if await self._media_storage_gateway.exists(normalized_path):
                return normalized_path
            if os.path.exists(normalized_path) is not True:
                return None
            return await self._media_storage_gateway.store_file(
                normalized_path,
                filename_hint=(
                    str(filename)
                    if filename not in [None, ""]
                    else None
                ),
            )

        payload_bytes = self._read_media_bytes(file_path)
        if payload_bytes is None:
            return None

        return await self._media_storage_gateway.store_bytes(
            payload_bytes,
            filename_hint=(
                str(filename)
                if filename not in [None, ""]
                else None
            ),
        )

    async def _persist_media_reference(
        self,
        *,
        file_path: Any,
        filename_hint: Any = None,
    ) -> str | None:
        if not isinstance(file_path, str) or file_path.strip() == "":
            return None

        persisted_ref = await self._resolve_media_source_path(
            file_path=file_path,
            filename=filename_hint,
        )
        if persisted_ref is None:
            return None

        normalized_input_path = os.path.abspath(file_path)
        if persisted_ref == normalized_input_path:
            return persisted_ref

        managed_cleanup_candidate = self._resolve_managed_upload_cleanup_path(
            normalized_input_path
        )
        if managed_cleanup_candidate is None:
            if os.path.exists(normalized_input_path):
                self._logging_gateway.debug(
                    "Skipping media source cleanup for unmanaged path "
                    f"path={normalized_input_path!r}."
                )
            return persisted_ref

        try:
            os.remove(managed_cleanup_candidate)
        except OSError as exc:
            self._logging_gateway.warning(
                "Failed to cleanup managed media upload path "
                f"path={managed_cleanup_candidate!r} error={exc}"
            )

        return persisted_ref

    def _resolve_managed_upload_cleanup_path(self, file_path: str) -> str | None:
        if not isinstance(file_path, str) or file_path.strip() == "":
            return None

        try:
            resolved_input = Path(file_path).resolve()
            resolved_media_root = Path(self._media_storage_path).resolve()
        except OSError:
            return None

        try:
            resolved_input.relative_to(resolved_media_root)
        except ValueError:
            return None

        if resolved_input.is_file() is not True:
            return None

        return str(resolved_input)

    async def _materialize_media_reference(self, value: Any) -> str | None:
        if not isinstance(value, str) or value.strip() == "":
            return None
        return await self._media_storage_gateway.materialize(value.strip())

    async def _persist_composed_media_references(
        self,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        raw_attachments = metadata.get("attachments")
        if not isinstance(raw_attachments, list):
            return metadata

        normalized = dict(metadata)
        normalized_attachments: list[dict[str, Any]] = []
        for attachment in raw_attachments:
            if not isinstance(attachment, dict):
                raise ValueError("metadata.attachments items must be objects")

            persisted_file_path = await self._persist_media_reference(
                file_path=attachment.get("file_path"),
                filename_hint=attachment.get("original_filename"),
            )
            if persisted_file_path is None:
                raise ValueError("metadata.attachments[].file_path is invalid")

            normalized_attachment = dict(attachment)
            normalized_attachment["file_path"] = persisted_file_path
            normalized_attachments.append(normalized_attachment)

        normalized["attachments"] = normalized_attachments
        return normalized

    @staticmethod
    def _read_media_bytes(value: Any) -> bytes | None:
        if isinstance(value, bytes):
            return value

        if isinstance(value, bytearray):
            return bytes(value)

        if isinstance(value, memoryview):
            return value.tobytes()

        if not isinstance(value, io.IOBase):
            return None

        read_fn = getattr(value, "read", None)
        if not callable(read_fn):
            return None

        seek_fn = getattr(value, "seek", None)
        tell_fn = getattr(value, "tell", None)
        start_pos: int | None = None
        if callable(tell_fn):
            try:
                start_pos = int(tell_fn())
            except (TypeError, ValueError, OSError):
                start_pos = None

        try:
            raw_data = read_fn()
        except (OSError, ValueError):
            return None
        finally:
            if start_pos is not None and callable(seek_fn):
                try:
                    seek_fn(start_pos)
                except (OSError, ValueError):
                    ...

        if isinstance(raw_data, bytes):
            return raw_data

        if isinstance(raw_data, bytearray):
            return bytes(raw_data)

        if isinstance(raw_data, memoryview):
            return raw_data.tobytes()

        if isinstance(raw_data, str):
            return raw_data.encode("utf-8")

        return None

    @staticmethod
    def _infer_media_extension(filename: Any) -> str:
        if not isinstance(filename, str):
            return ""

        _, extension = os.path.splitext(filename.strip())
        if extension == "" or len(extension) > 16:
            return ""

        return extension.lower()

    async def _append_event(
        self,
        *,
        conversation_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        event_entry: dict[str, Any]

        async with self._storage_lock:
            normalized_data = self._normalize_event_payload_with_correlation(
                conversation_id=conversation_id,
                event_type=event_type,
                data=data,
            )
            created_at_iso = self._utc_now_iso()
            created_at_dt = self._iso_to_utc_datetime(created_at_iso) or self._to_utc_datetime(
                self._epoch_now()
            )

            async with self._relational_session() as session:
                state_result = await session.execute(
                    web_sql_text(
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
                        web_sql_text(
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
                            "stream_version": self._event_log_version,
                        },
                    )
                    state_result = await session.execute(
                        web_sql_text(
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
                    fallback=self._new_stream_generation(),
                )
                try:
                    event_id = int(state.get("next_event_id"))
                except (TypeError, ValueError):
                    event_id = 1
                if event_id <= 0:
                    event_id = 1

                await session.execute(
                    web_sql_text(
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
                        "payload": json.dumps(
                            normalized_data, ensure_ascii=True, separators=(",", ":")
                        ),
                        "stream_generation": stream_generation,
                        "stream_version": self._event_log_version,
                        "created_at": created_at_dt,
                    },
                )

                await session.execute(
                    web_sql_text(
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
                        "stream_version": self._event_log_version,
                        "conversation_id": conversation_id,
                    },
                )

                min_keep_event_id = max(
                    event_id - self._sse_replay_max_events + 1,
                    1,
                )
                await session.execute(
                    web_sql_text(
                        "DELETE FROM mugen.web_conversation_event "
                        "WHERE conversation_id = :conversation_id "
                        "AND event_id < :min_keep_event_id"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "min_keep_event_id": min_keep_event_id,
                    },
                )

            event_entry = {
                "id": str(event_id),
                "event": event_type,
                "data": normalized_data,
                "created_at": created_at_iso,
                "stream_generation": stream_generation,
                "stream_version": self._event_log_version,
            }

        await self._publish_event(conversation_id, event_entry)
        return event_entry

    async def _publish_event(
        self,
        conversation_id: str,
        event_entry: dict[str, Any],
    ) -> None:
        async with self._subscriber_lock:
            subscribers = list(self._subscribers.get(conversation_id, set()))

        for subscriber in subscribers:
            try:
                await asyncio.wait_for(
                    subscriber.put(event_entry),
                    timeout=self._sse_enqueue_timeout_seconds,
                )
            except asyncio.TimeoutError:
                self._log_sse_diagnostic(
                    conversation_id=conversation_id,
                    incoming_event_id=event_entry.get("id"),
                    last_event_id=None,
                    reason="subscriber_enqueue_timeout_disconnect",
                    warning=True,
                )
                await self._disconnect_subscriber_for_backpressure(
                    conversation_id=conversation_id,
                    subscriber=subscriber,
                )

    async def _disconnect_subscriber_for_backpressure(
        self,
        *,
        conversation_id: str,
        subscriber: asyncio.Queue,
    ) -> None:
        await self._unregister_subscriber(conversation_id, subscriber)

        # Force the streaming loop to exit so the client reconnects and replays
        # from durable event storage.
        try:
            subscriber.put_nowait(self._sse_disconnect_sentinel)
            return
        except asyncio.QueueFull:
            ...

        while True:
            try:
                subscriber.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                subscriber.put_nowait(self._sse_disconnect_sentinel)
                return
            except asyncio.QueueFull:
                ...

        self._logging_gateway.warning(
            "Failed to enqueue SSE disconnect sentinel for lagging subscriber."
        )

    async def _register_subscriber(
        self,
        conversation_id: str,
        subscriber: asyncio.Queue,
    ) -> None:
        async with self._subscriber_lock:
            if conversation_id not in self._subscribers:
                self._subscribers[conversation_id] = set()
            self._subscribers[conversation_id].add(subscriber)

    async def _unregister_subscriber(
        self,
        conversation_id: str,
        subscriber: asyncio.Queue,
    ) -> None:
        async with self._subscriber_lock:
            subscribers = self._subscribers.get(conversation_id)
            if subscribers is None:
                return

            subscribers.discard(subscriber)
            if not subscribers:
                del self._subscribers[conversation_id]

    async def _cleanup_media_tokens_and_files(self) -> None:
        active_refs: set[str] = set()
        now_epoch = self._epoch_now()

        async with self._storage_lock:
            async with self._relational_session() as session:
                result = await session.execute(
                    web_sql_text(
                        "SELECT token, file_path, expires_at "
                        "FROM mugen.web_media_token"
                    )
                )
                for row in result.mappings().all():
                    token = row.get("token")
                    expires_at = self._datetime_to_epoch(row.get("expires_at"))
                    if expires_at is None or expires_at <= now_epoch:
                        await session.execute(
                            web_sql_text(
                                "DELETE FROM mugen.web_media_token "
                                "WHERE token = :token"
                            ),
                            {"token": token},
                        )
                        continue

                    file_path = row.get("file_path")
                    if isinstance(file_path, str) and file_path != "":
                        active_refs.add(file_path)

                queue_result = await session.execute(
                    web_sql_text(
                        "SELECT payload "
                        "FROM mugen.web_queue_job "
                        "WHERE status IN ('pending', 'processing')"
                    )
                )
                for row in queue_result.mappings().all():
                    active_refs.update(
                        self._collect_media_refs_from_queue_payload(row.get("payload"))
                    )

        await self._media_storage_gateway.cleanup(
            active_refs=active_refs,
            retention_seconds=self._media_retention_seconds,
            now_epoch=now_epoch,
        )

    @staticmethod
    def _normalise_media_ref(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if normalized == "":
            return None
        return normalized

    def _collect_media_refs_from_queue_payload(self, payload: Any) -> set[str]:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return set()
        if not isinstance(payload, dict):
            return set()

        refs: set[str] = set()
        file_path = self._normalise_media_ref(payload.get("file_path"))
        if file_path is not None:
            refs.add(file_path)
        refs.update(
            self._collect_media_refs_from_composed_metadata(
                payload.get("metadata")
            )
        )
        return refs

    def _collect_media_refs_from_queued_job(self, queue_job: Any) -> set[str]:
        if not isinstance(queue_job, dict):
            return set()

        refs: set[str] = set()
        file_path = self._normalise_media_ref(queue_job.get("file_path"))
        if file_path is not None:
            refs.add(file_path)
        refs.update(
            self._collect_media_refs_from_composed_metadata(
                queue_job.get("metadata")
            )
        )
        return refs

    def _collect_media_refs_from_composed_metadata(self, metadata: Any) -> set[str]:
        if not isinstance(metadata, dict):
            return set()

        attachments = metadata.get("attachments")
        if not isinstance(attachments, list):
            return set()

        refs: set[str] = set()
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            file_path = self._normalise_media_ref(attachment.get("file_path"))
            if file_path is not None:
                refs.add(file_path)
        return refs

    async def _mark_job_done(
        self,
        job_id: str,
        *,
        expected_attempt: int | None = None,
    ) -> None:
        await self._mark_job_status(
            job_id,
            status="done",
            error=None,
            expected_attempt=expected_attempt,
        )

    async def _mark_job_failed(
        self,
        job_id: str,
        error: str,
        *,
        expected_attempt: int | None = None,
    ) -> None:
        await self._mark_job_status(
            job_id,
            status="failed",
            error=error,
            expected_attempt=expected_attempt,
        )

    def _can_apply_terminal_queue_transition(
        self,
        *,
        job_id: str,
        current_status: Any,
        next_status: str,
    ) -> bool:
        if next_status not in {"done", "failed"}:
            return True

        normalized_current_status = str(current_status or "").strip().lower()
        if normalized_current_status == "processing":
            return True

        self._logging_gateway.warning(
            "Skipping queue status transition that violates lifecycle invariant "
            f"job_id={job_id} current_status={normalized_current_status!r} "
            f"next_status={next_status!r}."
        )
        return False

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

    async def _mark_job_status(
        self,
        job_id: str,
        *,
        status: str,
        error: str | None,
        expected_attempt: int | None = None,
    ) -> None:
        normalized_status = str(status).strip().lower()
        now_iso = self._utc_now_iso()
        async with self._storage_lock:
            async with self._relational_session() as session:
                result = await session.execute(
                    web_sql_text(
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
                    return

                current_job = self._queue_job_record_to_payload(row)
                if not self._can_apply_terminal_queue_transition(
                    job_id=job_id,
                    current_status=current_job.get("status"),
                    next_status=normalized_status,
                ):
                    return

                transitioned = self._apply_queue_job_status_transition(
                    job=current_job,
                    status=normalized_status,
                    error=error,
                    now_iso=now_iso,
                )
                update_sql = (
                    "UPDATE mugen.web_queue_job "
                    "SET status = CAST(:status AS mugen.citext), "
                    "lease_expires_at = NULL, "
                    "updated_at = :updated_at, "
                    "error_message = :error_message, "
                    "completed_at = :completed_at "
                )
                update_params = {
                    "status": str(transitioned.get("status", normalized_status)),
                    "updated_at": (
                        self._iso_to_utc_datetime(transitioned.get("updated_at"))
                        or self._to_utc_datetime(self._epoch_now())
                    ),
                    "error_message": (
                        str(transitioned.get("error"))
                        if transitioned.get("error") not in [None, ""]
                        else None
                    ),
                    "completed_at": self._iso_to_utc_datetime(
                        transitioned.get("completed_at")
                    ),
                    "job_id": job_id,
                }
                if normalized_status in {"done", "failed"}:
                    update_sql += (
                        "WHERE job_id = :job_id "
                        "AND status = CAST(:current_status AS mugen.citext) "
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
                    web_sql_text(update_sql),
                    update_params,
                )
                if (
                    normalized_status in {"done", "failed"}
                    and getattr(update_result, "rowcount", None) == 0
                ):
                    self._logging_gateway.warning(
                        "Skipped queue terminal transition due to relational "
                        f"precondition mismatch job_id={job_id} "
                        f"next_status={normalized_status!r}."
                    )
            return

    async def _recover_stale_processing_jobs_unlocked(self) -> None:
        now_epoch = self._epoch_now()
        async with self._relational_session() as session:
            recovered_result = await session.execute(
                web_sql_text(
                    "UPDATE mugen.web_queue_job "
                    "SET status = 'pending', lease_expires_at = NULL, updated_at = now() "
                    "WHERE status = 'processing' "
                    "AND (lease_expires_at IS NULL OR lease_expires_at <= :now_ts)"
                ),
                {"now_ts": self._to_utc_datetime(now_epoch)},
            )
        recovered_count = int(getattr(recovered_result, "rowcount", 0) or 0)
        if recovered_count > 0:
            self._logging_gateway.warning(
                "Web client recovered stale processing jobs on startup "
                f"(count={recovered_count})."
            )

    async def _ensure_conversation_owner_unlocked(
        self,
        *,
        conversation_id: str,
        auth_user: str,
        create_if_missing: bool,
    ) -> None:
        async with self._relational_session() as session:
            result = await session.execute(
                web_sql_text(
                    "SELECT owner_user_id "
                    "FROM mugen.web_conversation_state "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            row = result.mappings().one_or_none()
            if row is None:
                if not create_if_missing:
                    raise KeyError("conversation not found")

                await session.execute(
                    web_sql_text(
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
                        "stream_generation": self._new_stream_generation(),
                        "stream_version": self._event_log_version,
                    },
                )

                result = await session.execute(
                    web_sql_text(
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

    async def _read_replay_events_unlocked(
        self,
        *,
        conversation_id: str,
        last_event_id: str | None,
    ) -> list[dict[str, Any]]:
        log = await self._read_event_log_unlocked(conversation_id)
        events = list(log["events"])

        lower_bound = self._parse_event_id(last_event_id)
        if lower_bound is None:
            return events

        return [
            event
            for event in events
            if (self._parse_event_id(event.get("id")) or 0) > lower_bound
        ]

    async def _read_queue_state_unlocked(self) -> dict[str, Any]:
        async with self._relational_session() as session:
            result = await session.execute(
                web_sql_text(
                    "SELECT job_id, conversation_id, sender, message_type, payload, "
                    "status, attempts, created_at, updated_at, lease_expires_at, "
                    "error_message, completed_at, client_message_id "
                    "FROM mugen.web_queue_job "
                    "ORDER BY created_at ASC"
                )
            )
            jobs = [
                self._queue_job_record_to_payload(row)
                for row in result.mappings().all()
            ]
        return {
            "version": self._queue_state_version,
            "jobs": jobs,
        }

    async def _write_queue_state_unlocked(self, queue_state: dict[str, Any]) -> None:
        jobs = queue_state.get("jobs", []) if isinstance(queue_state, dict) else []
        if not isinstance(jobs, list):
            jobs = []

        async with self._relational_session() as session:
            await session.execute(web_sql_text("DELETE FROM mugen.web_queue_job"))
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
                    web_sql_text(
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
                        "payload": json.dumps(
                            payload, ensure_ascii=True, separators=(",", ":")
                        ),
                        "status": str(job.get("status", "pending")),
                        "attempts": int(job.get("attempts") or 0),
                        "lease_expires_at": (
                            self._to_utc_datetime(
                                float(job.get("lease_expires_at"))
                            )
                            if self._coerce_float(job.get("lease_expires_at"))
                            is not None
                            else None
                        ),
                        "error_message": (
                            str(job.get("error"))
                            if job.get("error") not in [None, ""]
                            else None
                        ),
                        "completed_at": self._iso_to_utc_datetime(
                            job.get("completed_at")
                        ),
                        "client_message_id": (
                            str(job.get("client_message_id"))
                            if job.get("client_message_id") not in [None, ""]
                            else None
                        ),
                        "created_at": self._iso_to_utc_datetime(job.get("created_at"))
                        or self._to_utc_datetime(self._epoch_now()),
                        "updated_at": self._iso_to_utc_datetime(job.get("updated_at"))
                        or self._to_utc_datetime(self._epoch_now()),
                    },
                )

    async def _read_event_log_unlocked(self, conversation_id: str) -> dict[str, Any]:
        async with self._relational_session() as session:
            state_result = await session.execute(
                web_sql_text(
                    "SELECT stream_generation, stream_version, next_event_id "
                    "FROM mugen.web_conversation_state "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            state = state_result.mappings().one_or_none()
            if state is None:
                return self._new_event_log_state()

            raw_version = state.get("stream_version")
            try:
                parsed_version = int(raw_version)
            except (TypeError, ValueError):
                parsed_version = None

            if parsed_version != self._event_log_version:
                self._logging_gateway.warning(
                    "Web event log version mismatch; resetting conversation stream log "
                    f"(conversation_id={conversation_id} stored_version={raw_version!r} "
                    f"expected_version={self._event_log_version})."
                )
                return self._new_event_log_state()

            events_result = await session.execute(
                web_sql_text(
                    "SELECT event_id, event_type, payload, created_at, stream_generation, "
                    "stream_version "
                    "FROM mugen.web_conversation_event "
                    "WHERE conversation_id = :conversation_id "
                    "ORDER BY event_id DESC "
                    "LIMIT :event_limit"
                ),
                {
                    "conversation_id": conversation_id,
                    "event_limit": self._sse_replay_max_events,
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
                                fallback=self._new_stream_generation(),
                            ),
                        ),
                        "stream_version": int(
                            row.get("stream_version") or self._event_log_version
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
                "version": self._event_log_version,
                "generation": self._normalize_stream_generation(
                    state.get("stream_generation"),
                    fallback=self._new_stream_generation(),
                ),
                "next_event_id": next_id,
                "events": events,
            }

    async def _write_event_log_unlocked(
        self,
        conversation_id: str,
        payload: dict[str, Any],
    ) -> None:
        generation = self._normalize_stream_generation(
            payload.get("generation"),
            fallback=self._new_stream_generation(),
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
                web_sql_text(
                    "SELECT owner_user_id "
                    "FROM mugen.web_conversation_state "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            )
            owner_row = owner_result.mappings().one_or_none()
            owner_user_id = (
                owner_row.get("owner_user_id")
                if owner_row is not None
                else "system"
            )

            await session.execute(
                web_sql_text(
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
                    "stream_version": self._event_log_version,
                    "next_event_id": next_event_id,
                },
            )

            await session.execute(
                web_sql_text(
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
                    web_sql_text(
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
                            event.get("stream_version") or self._event_log_version
                        ),
                        "created_at": self._iso_to_utc_datetime(
                            event.get("created_at")
                        )
                        or self._to_utc_datetime(self._epoch_now()),
                    },
                )

    def _resolve_allowed_mimetypes(self) -> list[str]:
        raw_mimetypes = self._resolve_config_path(("web", "media", "allowed_mimetypes"))
        if not isinstance(raw_mimetypes, list):
            return list(self._default_media_allowed_mimetypes)

        normalized: list[str] = []
        for item in raw_mimetypes:
            if not isinstance(item, str):
                continue

            candidate = item.strip().lower()
            if candidate == "":
                continue
            normalized.append(candidate)

        if not normalized:
            return list(self._default_media_allowed_mimetypes)

        return normalized

    def _resolve_storage_path(self, configured_path: str) -> str:
        if os.path.isabs(configured_path):
            return configured_path

        basedir = getattr(self._config, "basedir", None)
        if isinstance(basedir, str) and basedir != "":
            return os.path.abspath(os.path.join(basedir, configured_path))

        return os.path.abspath(configured_path)

    def _build_media_storage_gateway(self) -> IMediaStorageGateway:
        if self._media_backend in {"filesystem", "fs", "local"}:
            return FilesystemMediaStorageGateway(base_path=self._media_storage_path)

        if self._media_backend in {"object", "object_storage", "keyval"}:
            raw_cache_path = self._resolve_str_config(
                ("web", "media", "object", "cache_path"),
                self._default_media_object_cache_path,
            )
            raw_key_prefix = self._resolve_str_config(
                ("web", "media", "object", "key_prefix"),
                "web:media:object",
            )
            return ObjectMediaStorageGateway(
                keyval_storage_gateway=self._keyval_storage_gateway,
                cache_path=self._resolve_storage_path(raw_cache_path),
                key_prefix=raw_key_prefix,
            )

        raise ValueError(
            "web.media.backend must be one of: filesystem, object."
        )

    def _ensure_media_directory(self) -> None:
        if self._media_backend in {"filesystem", "fs", "local"}:
            Path(self._media_storage_path).mkdir(parents=True, exist_ok=True)

    def _resolve_float_config(
        self,
        path: tuple[str, ...],
        default: float,
        *,
        minimum: float,
    ) -> float:
        raw_value = self._resolve_config_path(path)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = default

        if value < minimum:
            return default

        return value

    def _resolve_int_config(
        self,
        path: tuple[str, ...],
        default: int,
        *,
        minimum: int,
    ) -> int:
        raw_value = self._resolve_config_path(path)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default

        if value < minimum:
            return default

        return value

    def _resolve_str_config(
        self,
        path: tuple[str, ...],
        default: str,
    ) -> str:
        raw_value = self._resolve_config_path(path)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            return default
        return raw_value.strip()

    def _resolve_config_path(self, path: tuple[str, ...]) -> Any:
        node: Any = self._config
        for item in path:
            node = getattr(node, item, None)
            if node is None:
                return None
        return node

    @staticmethod
    def _require_non_empty(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a non-empty string")

        normalized = value.strip()
        if normalized == "":
            raise ValueError(f"{field_name} must be a non-empty string")

        return normalized

    def _normalize_message_type(self, message_type: str) -> str:
        normalized = self._require_non_empty(message_type, "message_type").lower()
        if normalized not in self._accepted_message_types:
            raise ValueError(f"Unsupported message_type: {normalized}")
        return normalized

    def _normalize_composed_metadata(self, metadata: Any) -> dict[str, Any]:
        try:
            normalized = NormalizeComposedMessageUseCase(
                max_attachments=self._media_max_attachments_per_message,
            ).handle(metadata)
        except ValueError as exc:
            message = str(exc)
            if message.startswith("message."):
                message = f"metadata.{message[len('message.'):]}"
            elif message.startswith("message "):
                message = f"metadata {message[len('message '):]}"
            raise ValueError(message) from exc
        return normalized

    def _normalize_client_message_id(
        self,
        *,
        client_message_id: str | None,
        job_id: str,
        conversation_id: str,
        source: str,
        event_type: str,
    ) -> str:
        if isinstance(client_message_id, str):
            normalized = client_message_id.strip()
            if normalized != "":
                return normalized

        fallback_client_message_id = f"auto-{job_id}"
        self._logging_gateway.warning(
            "Web event correlation defaulted missing client_message_id "
            f"(source={source} event_type={event_type} "
            f"conversation_id={conversation_id} job_id={job_id} "
            f"fallback_client_message_id={fallback_client_message_id})."
        )
        return fallback_client_message_id

    def _normalize_event_payload_with_correlation(
        self,
        *,
        conversation_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("event data must be an object")

        normalized_data = dict(data)
        if event_type not in self._required_correlation_event_types:
            return normalized_data

        missing_keys: list[str] = []
        for key in ("job_id", "client_message_id"):
            if key not in normalized_data:
                normalized_data[key] = None
                missing_keys.append(key)

        if missing_keys:
            self._logging_gateway.warning(
                "Web event correlation keys missing; defaulted to null "
                f"(conversation_id={conversation_id} event_type={event_type} "
                f"missing_keys={missing_keys})."
            )

        for key in ("job_id", "client_message_id"):
            value = normalized_data.get(key)
            if value is None:
                continue

            if isinstance(value, str):
                stripped_value = value.strip()
                if stripped_value == "":
                    normalized_data[key] = None
                    self._logging_gateway.warning(
                        "Web event correlation value blank; defaulted to null "
                        f"(conversation_id={conversation_id} event_type={event_type} "
                        f"correlation_key={key})."
                    )
                else:
                    normalized_data[key] = stripped_value
                continue

            normalized_data[key] = str(value)
            self._logging_gateway.warning(
                "Web event correlation value coerced to string "
                f"(conversation_id={conversation_id} event_type={event_type} "
                f"correlation_key={key})."
            )

        return normalized_data

    def _build_stream_sse_event(
        self,
        *,
        event: dict[str, Any],
        stream_generation: str,
    ) -> dict[str, Any]:
        stream_event = copy.deepcopy(event)
        event_type = str(stream_event.get("event", "message"))
        event_data = stream_event.get("data")
        if not isinstance(event_data, dict):
            event_data = {"payload": event_data}
        conversation_id = event_data.get("conversation_id")
        if not isinstance(conversation_id, str):
            conversation_id = ""

        normalized_data = self._normalize_event_payload_with_correlation(
            conversation_id=conversation_id,
            event_type=event_type,
            data=event_data,
        )
        normalized_data["_stream"] = {
            "version": self._event_log_version,
            "generation": stream_generation,
        }
        stream_event["data"] = normalized_data

        numeric_event_id = self._parse_event_id(stream_event.get("id"))
        if numeric_event_id is not None:
            stream_event["id"] = self._format_stream_cursor_id(
                stream_generation=stream_generation,
                event_id=numeric_event_id,
            )
        elif "id" in stream_event and stream_event["id"] is not None:
            stream_event["id"] = str(stream_event["id"])
        else:
            stream_event["id"] = ""

        stream_event["stream_generation"] = stream_generation
        stream_event["stream_version"] = self._event_log_version
        return stream_event

    def _build_stream_reset_event(
        self,
        *,
        conversation_id: str,
        reason: str,
        incoming_last_event_id: str | None,
        incoming_event_id: int | None,
        stream_generation: str,
    ) -> dict[str, Any]:
        reset_event = {
            "id": "0",
            "event": "system",
            "data": {
                "job_id": None,
                "client_message_id": None,
                "signal": self._stream_reset_signal,
                "message": "Event stream cursor reset.",
                "conversation_id": conversation_id,
                "incoming_last_event_id": incoming_last_event_id,
                "incoming_event_id": incoming_event_id,
                "reason": reason,
                "event_log_version": self._event_log_version,
                "event_log_generation": stream_generation,
            },
            "created_at": self._utc_now_iso(),
            "stream_generation": stream_generation,
            "stream_version": self._event_log_version,
        }
        return self._build_stream_sse_event(
            event=reset_event,
            stream_generation=stream_generation,
        )

    def _resolve_stream_cursor(
        self,
        *,
        conversation_id: str,
        incoming_last_event_id: str | None,
        stream_generation: str,
        max_event_id: int,
    ) -> dict[str, Any]:
        parsed_cursor = self._parse_stream_cursor(incoming_last_event_id)

        incoming_event_id = parsed_cursor.get("event_id")
        effective_last_event_id = int(incoming_event_id or 0)
        reset_reason: str | None = None

        if parsed_cursor.get("invalid"):
            reset_reason = "invalid_last_event_id"
        elif parsed_cursor.get("stream_generation") is not None:
            if parsed_cursor.get("stream_version") != self._event_log_version:
                reset_reason = "cursor_event_log_version_mismatch"
            elif parsed_cursor.get("stream_generation") != stream_generation:
                reset_reason = "cursor_stream_generation_mismatch"
        elif incoming_event_id is not None and incoming_event_id > max_event_id:
            reset_reason = "legacy_cursor_ahead_of_stream"

        if reset_reason is None:
            return {
                "effective_last_event_id": effective_last_event_id,
                "incoming_event_id": incoming_event_id,
                "reset_event": None,
            }

        self._log_sse_diagnostic(
            conversation_id=conversation_id,
            incoming_event_id=incoming_event_id,
            last_event_id=incoming_last_event_id,
            reason=reset_reason,
            warning=True,
        )

        return {
            "effective_last_event_id": 0,
            "incoming_event_id": incoming_event_id,
            "reset_event": self._build_stream_reset_event(
                conversation_id=conversation_id,
                reason=reset_reason,
                incoming_last_event_id=incoming_last_event_id,
                incoming_event_id=incoming_event_id,
                stream_generation=stream_generation,
            ),
        }

    def _parse_stream_cursor(self, last_event_id: str | None) -> dict[str, Any]:
        parsed: dict[str, Any] = {
            "raw": last_event_id,
            "stream_version": None,
            "stream_generation": None,
            "event_id": None,
            "invalid": False,
        }
        if not isinstance(last_event_id, str):
            return parsed

        raw_cursor = last_event_id.strip()
        parsed["raw"] = raw_cursor
        if raw_cursor == "":
            return parsed

        cursor_parts = raw_cursor.split(":", 2)
        if len(cursor_parts) == 3 and cursor_parts[0].startswith("v"):
            try:
                stream_version = int(cursor_parts[0][1:])
            except (TypeError, ValueError):
                parsed["invalid"] = True
                return parsed

            stream_generation = cursor_parts[1].strip()
            stream_event_id = self._parse_event_id(cursor_parts[2])
            if (
                stream_version <= 0
                or stream_generation == ""
                or stream_event_id is None
            ):
                parsed["invalid"] = True
                return parsed

            parsed["stream_version"] = stream_version
            parsed["stream_generation"] = stream_generation
            parsed["event_id"] = stream_event_id
            return parsed

        parsed_event_id = self._parse_event_id(raw_cursor)
        if parsed_event_id is None:
            parsed["invalid"] = True
            return parsed

        parsed["event_id"] = parsed_event_id
        return parsed

    def _format_stream_cursor_id(
        self,
        *,
        stream_generation: str,
        event_id: int,
    ) -> str:
        return f"v{self._event_log_version}:{stream_generation}:{event_id}"

    @staticmethod
    def _normalize_stream_generation(value: Any, *, fallback: str) -> str:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized != "":
                return normalized.replace(":", "-")
        return fallback

    def _log_sse_diagnostic(
        self,
        *,
        conversation_id: str,
        incoming_event_id: Any,
        last_event_id: Any,
        reason: str,
        warning: bool = False,
    ) -> None:
        message = (
            "Web SSE event skipped/dropped "
            f"(conversation_id={conversation_id!r} "
            f"incoming_event_id={incoming_event_id!r} "
            f"last_event_id={last_event_id!r} "
            f"reason={reason!r})."
        )
        if warning:
            self._logging_gateway.warning(message)
        else:
            self._logging_gateway.debug(message)

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
    def _format_sse_event(event: dict[str, Any]) -> str:
        event_id = str(event.get("id", ""))
        event_type = str(event.get("event", "message"))
        data_json = json.dumps(event.get("data", {}), separators=(",", ":"))

        lines = [
            f"id: {event_id}",
            f"event: {event_type}",
        ]
        for line in data_json.splitlines() or [data_json]:
            lines.append(f"data: {line}")

        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _epoch_now() -> float:
        return datetime.now(timezone.utc).timestamp()

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _new_stream_generation() -> str:
        return uuid.uuid4().hex

    @classmethod
    def _new_event_log_state(cls) -> dict[str, Any]:
        return {
            "version": cls._event_log_version,
            "generation": cls._new_stream_generation(),
            "next_event_id": 1,
            "events": [],
        }
