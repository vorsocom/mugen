"""Provides an implementation of IWebClient."""

__all__ = ["DefaultWebClient"]

import asyncio
from collections.abc import AsyncIterator
import copy
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import uuid

from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


# pylint: disable=too-many-instance-attributes
class DefaultWebClient(IWebClient):
    """An implementation of IWebClient."""

    _accepted_message_types = {
        "text",
        "audio",
        "video",
        "file",
        "image",
    }

    _queue_state_key = "web:queue"
    _queue_state_version = 1

    _conversation_key_prefix = "web:conversation:"

    _event_log_key_prefix = "web:events:"
    _event_log_version = 1

    _media_token_key_prefix = "web:media_token:"

    _default_sse_keepalive_seconds: float = 15.0
    _default_sse_replay_max_events: int = 200
    _default_queue_poll_interval_seconds: float = 0.25
    _default_queue_processing_lease_seconds: float = 30.0
    _default_queue_max_pending_jobs: int = 2000
    _default_media_storage_path: str = "data/web_media"
    _default_media_max_upload_bytes: int = 20 * 1024 * 1024
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
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        self._config = config
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

        self._storage_lock = asyncio.Lock()
        self._subscriber_lock = asyncio.Lock()
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

        self._worker_task: asyncio.Task | None = None
        self._worker_stop = asyncio.Event()

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

        self._media_max_upload_bytes = self._resolve_int_config(
            ("web", "media", "max_upload_bytes"),
            self._default_media_max_upload_bytes,
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

        async with self._storage_lock:
            self._recover_stale_processing_jobs_unlocked()

        if self._worker_task is not None and not self._worker_task.done():
            return

        self._worker_stop.clear()
        self._worker_task = asyncio.create_task(
            self._worker_loop(),
            name="mugen.web.worker",
        )

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
        auth_user_id = self._require_non_empty(auth_user, "auth_user")
        conversation = self._require_non_empty(conversation_id, "conversation_id")
        normalized_type = self._normalize_message_type(message_type)

        if normalized_type == "text":
            if text is None or str(text).strip() == "":
                raise ValueError("text is required for message_type=text")
        elif file_path in [None, ""]:
            raise ValueError(f"file is required for message_type={normalized_type}")

        payload_metadata: dict[str, Any] = {}
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            payload_metadata = dict(metadata)

        now_iso = self._utc_now_iso()
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "conversation_id": conversation,
            "sender": auth_user_id,
            "message_type": normalized_type,
            "text": text,
            "metadata": payload_metadata,
            "file_path": file_path,
            "mime_type": mime_type,
            "original_filename": original_filename,
            "client_message_id": client_message_id,
            "status": "pending",
            "attempts": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
            "lease_expires_at": None,
            "error": None,
        }

        async with self._storage_lock:
            self._ensure_conversation_owner_unlocked(
                conversation_id=conversation,
                auth_user=auth_user_id,
                create_if_missing=True,
            )

            queue_state = self._read_queue_state_unlocked()
            pending_count = sum(
                1
                for queue_job in queue_state["jobs"]
                if queue_job.get("status") == "pending"
            )
            if pending_count >= self._queue_max_pending_jobs:
                raise OverflowError("queue is full")

            queue_state["jobs"].append(job)
            self._write_queue_state_unlocked(queue_state)

        ack_payload = {
            "job_id": job_id,
            "conversation_id": conversation,
            "client_message_id": client_message_id,
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
            self._ensure_conversation_owner_unlocked(
                conversation_id=conversation,
                auth_user=auth_user_id,
                create_if_missing=False,
            )
            replay_events = self._read_replay_events_unlocked(
                conversation_id=conversation,
                last_event_id=last_event_id,
            )

        subscriber_queue: asyncio.Queue = asyncio.Queue(maxsize=self._sse_queue_size)
        await self._register_subscriber(conversation, subscriber_queue)

        async def _event_stream() -> AsyncIterator[str]:
            highest_event_id = self._parse_event_id(last_event_id) or 0
            try:
                for event in replay_events:
                    event_id = self._parse_event_id(event.get("id"))
                    if event_id is not None and event_id <= highest_event_id:
                        continue
                    if event_id is not None:
                        highest_event_id = event_id
                    yield self._format_sse_event(event)

                while True:
                    try:
                        event = await asyncio.wait_for(
                            subscriber_queue.get(),
                            timeout=self._sse_keepalive_seconds,
                        )
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue

                    event_id = self._parse_event_id(event.get("id"))
                    if event_id is not None and event_id <= highest_event_id:
                        continue
                    if event_id is not None:
                        highest_event_id = event_id
                    yield self._format_sse_event(event)
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
        token_key = self._media_token_key(token)

        async with self._storage_lock:
            token_data = self._read_json_unlocked(token_key)
            if not isinstance(token_data, dict):
                return None

            expires_at = self._coerce_float(token_data.get("expires_at"))
            if expires_at is None or expires_at <= self._epoch_now():
                self._keyval_storage_gateway.remove(token_key)
                return None

            owner_user_id = token_data.get("owner_user_id")
            if owner_user_id != auth_user_id:
                return None

            file_path = token_data.get("file_path")
            if not isinstance(file_path, str) or file_path == "":
                return None

            if not os.path.exists(file_path):
                self._keyval_storage_gateway.remove(token_key)
                return None

            return {
                "file_path": file_path,
                "mime_type": token_data.get("mime_type"),
                "filename": token_data.get("filename"),
            }

    @property
    def media_max_upload_bytes(self) -> int:
        """Expose configured upload size limit for API validators."""
        return self._media_max_upload_bytes

    @property
    def media_allowed_mimetypes(self) -> list[str]:
        """Expose configured upload mime allow-list for API validators."""
        return list(self._media_allowed_mimetypes)

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
            queue_state = self._read_queue_state_unlocked()
            jobs = queue_state["jobs"]
            changed = False

            for queue_job in jobs:
                if queue_job.get("status") != "processing":
                    continue

                lease_expires_at = self._coerce_float(queue_job.get("lease_expires_at"))
                if lease_expires_at is None or lease_expires_at <= now_epoch:
                    queue_job["status"] = "pending"
                    queue_job["lease_expires_at"] = None
                    queue_job["updated_at"] = now_iso
                    changed = True

            claimed_job: dict[str, Any] | None = None
            for queue_job in jobs:
                if queue_job.get("status") != "pending":
                    continue

                queue_job["status"] = "processing"
                queue_job["attempts"] = int(queue_job.get("attempts") or 0) + 1
                queue_job["updated_at"] = now_iso
                queue_job["lease_expires_at"] = (
                    now_epoch + self._queue_processing_lease_seconds
                )
                claimed_job = copy.deepcopy(queue_job)
                changed = True
                break

            if changed:
                self._write_queue_state_unlocked(queue_state)

            return claimed_job

    async def _process_claimed_job(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("id"))
        conversation_id = str(job.get("conversation_id"))
        sender = str(job.get("sender"))
        client_message_id = job.get("client_message_id")

        try:
            responses = await self._dispatch_job_to_messaging(job)

            if not responses:
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
                for response in responses:
                    event = await self._response_to_event(
                        response=response,
                        sender=sender,
                        conversation_id=conversation_id,
                    )

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

            await self._mark_job_done(job_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
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
            await self._mark_job_failed(job_id, str(exc))

    async def _dispatch_job_to_messaging(self, job: dict[str, Any]) -> list[dict] | None:
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

        message_payload = {
            "file_path": job.get("file_path"),
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

        if response_type not in self._accepted_message_types:
            return {
                "event_type": "error",
                "payload": {"error": f"Unsupported response type: {response_type}."},
            }

        content = response.get("content")
        if response_type == "text":
            return {
                "event_type": "message",
                "payload": {
                    "message": {
                        "type": "text",
                        "content": "" if content is None else str(content),
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
                        "Unsupported media response payload "
                        f"for type={response_type}."
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

            file_path = content.get("file_path") or content.get("path")
            mime_type = (
                content.get("mime_type")
                or content.get("mimetype")
                or fallback_mime_type
            )
            filename = content.get("filename") or content.get("name") or fallback_filename
            return await self._create_media_token_payload(
                file_path=file_path,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                mime_type=mime_type,
                filename=filename,
            )

        if isinstance(content, str) and content != "" and os.path.exists(content):
            return await self._create_media_token_payload(
                file_path=content,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                mime_type=fallback_mime_type,
                filename=fallback_filename,
            )

        return None

    async def _create_media_token_payload(
        self,
        *,
        file_path: Any,
        owner_user_id: str,
        conversation_id: str,
        mime_type: Any,
        filename: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(file_path, str) or file_path == "":
            return None

        normalized_path = os.path.abspath(file_path)
        if not os.path.exists(normalized_path):
            return None

        token = uuid.uuid4().hex
        expires_at = self._epoch_now() + self._media_download_token_ttl_seconds
        normalized_mime_type = (
            str(mime_type).strip() if mime_type not in [None, ""] else None
        )
        normalized_filename = (
            str(filename).strip()
            if filename not in [None, ""]
            else os.path.basename(normalized_path)
        )

        token_payload = {
            "owner_user_id": owner_user_id,
            "conversation_id": conversation_id,
            "file_path": normalized_path,
            "mime_type": normalized_mime_type,
            "filename": normalized_filename,
            "expires_at": expires_at,
        }

        async with self._storage_lock:
            self._write_json_unlocked(self._media_token_key(token), token_payload)

        return {
            "url": f"/api/core/web/v1/media/{token}",
            "token": token,
            "mime_type": normalized_mime_type,
            "filename": normalized_filename,
            "expires_at": expires_at,
        }

    async def _append_event(
        self,
        *,
        conversation_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        event_entry: dict[str, Any]

        async with self._storage_lock:
            log = self._read_event_log_unlocked(conversation_id)
            event_id = int(log["next_event_id"])
            event_entry = {
                "id": str(event_id),
                "event": event_type,
                "data": data,
                "created_at": self._utc_now_iso(),
            }

            log["next_event_id"] = event_id + 1
            events = list(log["events"])
            events.append(event_entry)
            if len(events) > self._sse_replay_max_events:
                events = events[-self._sse_replay_max_events :]
            log["events"] = events
            self._write_event_log_unlocked(conversation_id, log)

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
                subscriber.put_nowait(event_entry)
            except asyncio.QueueFull:
                try:
                    subscriber.get_nowait()
                except asyncio.QueueEmpty:
                    ...
                try:
                    subscriber.put_nowait(event_entry)
                except asyncio.QueueFull:
                    ...

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
        active_paths: set[str] = set()
        now_epoch = self._epoch_now()

        async with self._storage_lock:
            for key in self._keyval_storage_gateway.keys():
                if not key.startswith(self._media_token_key_prefix):
                    continue

                token_payload = self._read_json_unlocked(key)
                if not isinstance(token_payload, dict):
                    self._keyval_storage_gateway.remove(key)
                    continue

                expires_at = self._coerce_float(token_payload.get("expires_at"))
                if expires_at is None or expires_at <= now_epoch:
                    self._keyval_storage_gateway.remove(key)
                    continue

                file_path = token_payload.get("file_path")
                if isinstance(file_path, str) and file_path != "":
                    active_paths.add(os.path.abspath(file_path))

        try:
            file_names = os.listdir(self._media_storage_path)
        except (FileNotFoundError, NotADirectoryError):
            return

        for file_name in file_names:
            candidate = os.path.abspath(os.path.join(self._media_storage_path, file_name))
            if not os.path.isfile(candidate):
                continue

            if candidate in active_paths:
                continue

            try:
                age_seconds = now_epoch - os.path.getmtime(candidate)
            except OSError:
                continue

            if age_seconds < self._media_retention_seconds:
                continue

            try:
                os.remove(candidate)
            except OSError:
                ...

    async def _mark_job_done(self, job_id: str) -> None:
        await self._mark_job_status(job_id, status="done", error=None)

    async def _mark_job_failed(self, job_id: str, error: str) -> None:
        await self._mark_job_status(job_id, status="failed", error=error)

    async def _mark_job_status(
        self,
        job_id: str,
        *,
        status: str,
        error: str | None,
    ) -> None:
        async with self._storage_lock:
            queue_state = self._read_queue_state_unlocked()
            for queue_job in queue_state["jobs"]:
                if str(queue_job.get("id")) != job_id:
                    continue

                queue_job["status"] = status
                queue_job["lease_expires_at"] = None
                queue_job["updated_at"] = self._utc_now_iso()
                queue_job["error"] = error
                if status == "done":
                    queue_job["completed_at"] = self._utc_now_iso()
                self._write_queue_state_unlocked(queue_state)
                return

    def _recover_stale_processing_jobs_unlocked(self) -> None:
        now_epoch = self._epoch_now()
        now_iso = self._utc_now_iso()
        queue_state = self._read_queue_state_unlocked()
        changed = False
        for queue_job in queue_state["jobs"]:
            if queue_job.get("status") != "processing":
                continue

            lease_expires_at = self._coerce_float(queue_job.get("lease_expires_at"))
            if lease_expires_at is None or lease_expires_at <= now_epoch:
                queue_job["status"] = "pending"
                queue_job["lease_expires_at"] = None
                queue_job["updated_at"] = now_iso
                changed = True

        if changed:
            self._write_queue_state_unlocked(queue_state)

    def _ensure_conversation_owner_unlocked(
        self,
        *,
        conversation_id: str,
        auth_user: str,
        create_if_missing: bool,
    ) -> None:
        key = self._conversation_key(conversation_id)
        payload = self._read_json_unlocked(key)

        if not isinstance(payload, dict):
            if not create_if_missing:
                raise KeyError("conversation not found")

            self._write_json_unlocked(
                key,
                {
                    "owner_user_id": auth_user,
                    "created_at": self._utc_now_iso(),
                    "updated_at": self._utc_now_iso(),
                },
            )
            return

        owner_user_id = payload.get("owner_user_id")
        if owner_user_id != auth_user:
            raise PermissionError("conversation owner mismatch")

    def _read_replay_events_unlocked(
        self,
        *,
        conversation_id: str,
        last_event_id: str | None,
    ) -> list[dict[str, Any]]:
        log = self._read_event_log_unlocked(conversation_id)
        events = list(log["events"])

        lower_bound = self._parse_event_id(last_event_id)
        if lower_bound is None:
            return events

        return [
            event
            for event in events
            if (self._parse_event_id(event.get("id")) or 0) > lower_bound
        ]

    def _read_queue_state_unlocked(self) -> dict[str, Any]:
        payload = self._read_json_unlocked(self._queue_state_key)
        if not isinstance(payload, dict):
            return self._new_queue_state()

        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            jobs = []

        return {
            "version": self._queue_state_version,
            "jobs": jobs,
        }

    def _write_queue_state_unlocked(self, queue_state: dict[str, Any]) -> None:
        self._write_json_unlocked(self._queue_state_key, queue_state)

    def _read_event_log_unlocked(self, conversation_id: str) -> dict[str, Any]:
        key = self._event_log_key(conversation_id)
        payload = self._read_json_unlocked(key)
        if not isinstance(payload, dict):
            return self._new_event_log_state()

        events = payload.get("events")
        if not isinstance(events, list):
            events = []

        next_event_id = payload.get("next_event_id")
        try:
            next_id = int(next_event_id)
        except (TypeError, ValueError):
            next_id = 1

        if next_id <= 0:
            next_id = 1

        return {
            "version": self._event_log_version,
            "next_event_id": next_id,
            "events": events,
        }

    def _write_event_log_unlocked(
        self,
        conversation_id: str,
        payload: dict[str, Any],
    ) -> None:
        self._write_json_unlocked(self._event_log_key(conversation_id), payload)

    def _read_json_unlocked(self, key: str) -> dict[str, Any] | list[Any] | None:
        raw = self._keyval_storage_gateway.get(key)
        if raw in [None, ""]:
            return None

        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                self._logging_gateway.warning(
                    f"Web client state is not utf-8 decodable for key {key!r}."
                )
                return None

        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            self._logging_gateway.warning(f"Web client state is invalid for key {key!r}.")
            return None

        if isinstance(payload, (dict, list)):
            return payload

        return None

    def _write_json_unlocked(self, key: str, payload: dict[str, Any]) -> None:
        self._keyval_storage_gateway.put(
            key,
            json.dumps(payload, separators=(",", ":")),
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

    def _ensure_media_directory(self) -> None:
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

    @classmethod
    def _conversation_key(cls, conversation_id: str) -> str:
        return f"{cls._conversation_key_prefix}{conversation_id}"

    @classmethod
    def _event_log_key(cls, conversation_id: str) -> str:
        return f"{cls._event_log_key_prefix}{conversation_id}"

    @classmethod
    def _media_token_key(cls, token: str) -> str:
        return f"{cls._media_token_key_prefix}{token}"

    @classmethod
    def _new_queue_state(cls) -> dict[str, Any]:
        return {
            "version": cls._queue_state_version,
            "jobs": [],
        }

    @classmethod
    def _new_event_log_state(cls) -> dict[str, Any]:
        return {
            "version": cls._event_log_version,
            "next_event_id": 1,
            "events": [],
        }
