"""Unit tests for mugen.core.client.web.DefaultWebClient."""

from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.client.web import DefaultWebClient


class _InMemoryKeyVal:
    def __init__(self) -> None:
        self._store: dict[str, str | bytes] = {}

    def close(self) -> None:
        pass

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


def _build_config(*, basedir: str, replay_max_events: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        basedir=basedir,
        web=SimpleNamespace(
            sse=SimpleNamespace(
                keepalive_seconds=1,
                replay_max_events=replay_max_events,
            ),
            queue=SimpleNamespace(
                poll_interval_seconds=0.05,
                processing_lease_seconds=1,
                max_pending_jobs=100,
            ),
            media=SimpleNamespace(
                storage=SimpleNamespace(path="web_media"),
                max_upload_bytes=1024 * 1024,
                max_attachments_per_message=10,
                allowed_mimetypes=["image/*", "application/*", "text/*"],
                download_token_ttl_seconds=10,
                retention_seconds=1,
            ),
        ),
    )


class TestDefaultWebClient(unittest.IsolatedAsyncioTestCase):
    """Covers durable queue, replay, and media token behavior."""

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
        )

        self.client = DefaultWebClient(
            config=_build_config(basedir=self.tmpdir.name),
            ipc_service=Mock(),
            keyval_storage_gateway=self.keyval,
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.tmpdir.cleanup()

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
            queue = self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            self.assertEqual(queue["jobs"][0]["status"], "done")
            events = self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
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
            events = self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
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
            events = self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
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
        small_client = DefaultWebClient(
            config=_build_config(basedir=self.tmpdir.name, replay_max_events=2),
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
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
            events = small_client._read_replay_events_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-r",
                last_event_id=None,
            )
            replay_after_first = small_client._read_replay_events_unlocked(  # pylint: disable=protected-access
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
            queue = self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            queue["jobs"][0]["status"] = "processing"
            queue["jobs"][0]["lease_expires_at"] = 0
            self.client._write_queue_state_unlocked(queue)  # pylint: disable=protected-access
            self.client._recover_stale_processing_jobs_unlocked()  # pylint: disable=protected-access
            queue = self.client._read_queue_state_unlocked()  # pylint: disable=protected-access

        self.assertEqual(queue["jobs"][0]["status"], "pending")

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
            key = self.client._media_token_key(token)  # pylint: disable=protected-access
            payload = json.loads(self.keyval.get(key))
            payload["expires_at"] = 0
            self.keyval.put(key, json.dumps(payload))

        expired = await self.client.resolve_media_download(auth_user="user-1", token=token)
        self.assertIsNone(expired)

    async def test_media_cleanup_removes_expired_tokens_and_old_files(self) -> None:
        media_dir = Path(self.client._media_storage_path)  # pylint: disable=protected-access
        media_dir.mkdir(parents=True, exist_ok=True)

        old_file = media_dir / "old.bin"
        old_file.write_bytes(b"x")
        os.utime(old_file, (0, 0))

        active_file = media_dir / "active.bin"
        active_file.write_bytes(b"y")

        token_payload = await self.client._create_media_token_payload(  # pylint: disable=protected-access
            file_path=str(active_file),
            owner_user_id="user-1",
            conversation_id="conv-clean",
            mime_type="application/octet-stream",
            filename="active.bin",
        )

        expired_token_key = self.client._media_token_key("expired")  # pylint: disable=protected-access
        self.keyval.put(
            expired_token_key,
            json.dumps(
                {
                    "owner_user_id": "user-1",
                    "conversation_id": "conv-clean",
                    "file_path": str(old_file),
                    "mime_type": "application/octet-stream",
                    "filename": "old.bin",
                    "expires_at": 0,
                }
            ),
        )

        self.assertIsNotNone(token_payload)
        await self.client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        self.assertFalse(self.keyval.has_key(expired_token_key))
        self.assertFalse(old_file.exists())
        self.assertTrue(active_file.exists())

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
            events = self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
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
        loop_client = DefaultWebClient(
            config=_build_config(basedir=self.tmpdir.name),
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
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
        sleeper = DefaultWebClient(
            config=_build_config(basedir=self.tmpdir.name),
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
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

        self.client._sse_keepalive_seconds = 0.001  # pylint: disable=protected-access
        stream = await self.client.stream_events(
            auth_user="user-1",
            conversation_id="conv-stream",
            last_event_id="1",
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
            last_event_id="2",
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
            self.client._write_event_log_unlocked(  # pylint: disable=protected-access
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
            self.client._write_event_log_unlocked(  # pylint: disable=protected-access
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
        self.assertIn("id: bad", first_none_id)
        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-stream",
            {"id": "bad-live", "event": "system", "data": {}},
        )
        second_none_id = await none_id_stream.__anext__()
        self.assertIn("id: bad-live", second_none_id)
        await none_id_stream.aclose()

        # Missing conversation branch.
        with self.assertRaises(KeyError):
            await self.client.stream_events(
                auth_user="user-1",
                conversation_id="conv-missing",
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
            self.client._write_event_log_unlocked(  # pylint: disable=protected-access
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
        self.assertEqual(reset_payload["reason"], "legacy_cursor_ahead_of_stream")

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
            events = self.client._read_replay_events_unlocked(  # pylint: disable=protected-access
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
        class _AlwaysFullQueue:
            def put_nowait(self, _item):
                raise asyncio.QueueFull()

            def get_nowait(self):
                return {"id": "1"}

        async with self.client._subscriber_lock:  # pylint: disable=protected-access
            self.client._subscribers["conv-drop"] = {  # pylint: disable=protected-access
                _AlwaysFullQueue()
            }

        await self.client._publish_event(  # pylint: disable=protected-access
            "conv-drop",
            {"id": "2", "event": "system", "data": {}},
        )

        debug_messages = [call.args[0] for call in self.logger.debug.call_args_list]
        warning_messages = [call.args[0] for call in self.logger.warning.call_args_list]
        self.assertTrue(
            any(
                "Web SSE event skipped/dropped" in message
                and "conversation_id='conv-drop'" in message
                and "incoming_event_id='2'" in message
                and "last_event_id='1'" in message
                and "reason='subscriber_queue_full_drop_oldest'" in message
                for message in debug_messages
            )
        )
        self.assertTrue(
            any(
                "Web SSE event skipped/dropped" in message
                and "conversation_id='conv-drop'" in message
                and "incoming_event_id='2'" in message
                and "reason='subscriber_queue_full_drop_new'" in message
                for message in warning_messages
            )
        )

    async def test_stream_events_handles_non_positive_next_event_id(self) -> None:
        await self.client.enqueue_message(
            auth_user="user-1",
            conversation_id="conv-next-zero",
            message_type="text",
            text="hello",
            client_message_id="cid-next-zero",
        )

        async with self.client._storage_lock:  # pylint: disable=protected-access
            self.client._write_event_log_unlocked(  # pylint: disable=protected-access
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
            self.client._write_event_log_unlocked(  # pylint: disable=protected-access
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
        live_reset_chunk = await stream.__anext__()
        self.assertIn('"reason":"live_generation_changed"', live_reset_chunk)
        live_event_chunk = await stream.__anext__()
        self.assertIn(":gen-c:1", live_event_chunk)
        await stream.aclose()

        debug_messages = [call.args[0] for call in self.logger.debug.call_args_list]
        self.assertTrue(
            any(
                "reason='replay_event_id_not_greater_than_cursor'" in message
                for message in debug_messages
            )
        )

    async def test_stream_cursor_and_correlation_helper_branches(self) -> None:
        event_log_key = self.client._event_log_key("conv-helper")  # pylint: disable=protected-access
        self.keyval.put(
            event_log_key,
            json.dumps(
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "gen-helper",
                    "events": {},
                    "next_event_id": "bad",
                }
            ),
        )
        malformed_events = self.client._read_event_log_unlocked("conv-helper")  # pylint: disable=protected-access
        self.assertEqual(malformed_events["events"], [])
        self.assertEqual(malformed_events["next_event_id"], 1)

        self.keyval.put(
            event_log_key,
            json.dumps(
                {
                    "version": self.client._event_log_version,  # pylint: disable=protected-access
                    "generation": "gen-helper",
                    "events": [],
                    "next_event_id": -9,
                }
            ),
        )
        non_positive_next = self.client._read_event_log_unlocked("conv-helper")  # pylint: disable=protected-access
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
            max_event_id=0,
        )
        self.assertIsNotNone(invalid_cursor["reset_event"])

        version_mismatch_cursor = self.client._resolve_stream_cursor(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            incoming_last_event_id="v999:gen-helper:1",
            stream_generation="gen-helper",
            max_event_id=10,
        )
        self.assertIsNotNone(version_mismatch_cursor["reset_event"])

        generation_mismatch_cursor = self.client._resolve_stream_cursor(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            incoming_last_event_id=(
                f"v{self.client._event_log_version}:other-generation:1"  # pylint: disable=protected-access
            ),
            stream_generation="gen-helper",
            max_event_id=10,
        )
        self.assertIsNotNone(generation_mismatch_cursor["reset_event"])

        matching_cursor = self.client._resolve_stream_cursor(  # pylint: disable=protected-access
            conversation_id="conv-helper",
            incoming_last_event_id=(
                f"v{self.client._event_log_version}:gen-helper:1"  # pylint: disable=protected-access
            ),
            stream_generation="gen-helper",
            max_event_id=10,
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

        token_key = self.client._media_token_key("bad-token")  # pylint: disable=protected-access
        self.keyval.put(token_key, json.dumps({"expires_at": "NaN"}))
        self.assertIsNone(
            await self.client.resolve_media_download(auth_user="user-1", token="bad-token")
        )

        token_key = self.client._media_token_key("owner-mismatch")  # pylint: disable=protected-access
        self.keyval.put(
            token_key,
            json.dumps(
                {
                    "expires_at": 9999999999,
                    "owner_user_id": "other",
                    "file_path": "x",
                }
            ),
        )
        self.assertIsNone(
            await self.client.resolve_media_download(
                auth_user="user-1", token="owner-mismatch"
            )
        )

        token_key = self.client._media_token_key("empty-path")  # pylint: disable=protected-access
        self.keyval.put(
            token_key,
            json.dumps(
                {
                    "expires_at": 9999999999,
                    "owner_user_id": "user-1",
                    "file_path": "",
                }
            ),
        )
        self.assertIsNone(
            await self.client.resolve_media_download(auth_user="user-1", token="empty-path")
        )

        token_key = self.client._media_token_key("missing-file")  # pylint: disable=protected-access
        self.keyval.put(
            token_key,
            json.dumps(
                {
                    "expires_at": 9999999999,
                    "owner_user_id": "user-1",
                    "file_path": os.path.join(self.tmpdir.name, "missing.bin"),
                }
            ),
        )
        self.assertIsNone(
            await self.client.resolve_media_download(auth_user="user-1", token="missing-file")
        )

    async def test_dispatch_and_response_branches(self) -> None:
        job = {
            "conversation_id": "conv-d",
            "sender": "user-1",
            "metadata": {},
            "client_message_id": "cid",
            "file_path": "path",
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
        self.assertEqual(
            resolved_audio["file_path"],
            os.path.abspath(str(audio_file)),
        )

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
        self.assertTrue(
            resolved_buffer_audio["file_path"].endswith(".mp3"),
        )
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
        failing = DefaultWebClient(
            config=_build_config(basedir=self.tmpdir.name),
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
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
            failure_events = failing._read_replay_events_unlocked(  # pylint: disable=protected-access
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
            self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
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
        await self.client._register_subscriber("conv-sub", q1)  # pylint: disable=protected-access
        await self.client._register_subscriber("conv-sub", q2)  # pylint: disable=protected-access
        await self.client._register_subscriber("conv-sub", q1)  # pylint: disable=protected-access
        await self.client._unregister_subscriber("conv-sub", q1)  # pylint: disable=protected-access
        await self.client._unregister_subscriber("conv-sub", q2)  # pylint: disable=protected-access

        # Force QueueFull + QueueEmpty and second QueueFull branches.
        class _QueueAlwaysFull:
            def put_nowait(self, _item):
                raise asyncio.QueueFull()

            def get_nowait(self):
                raise asyncio.QueueEmpty()

        class _QueueStillFull:
            def __init__(self):
                self.calls = 0

            def put_nowait(self, _item):
                self.calls += 1
                raise asyncio.QueueFull()

            def get_nowait(self):
                return {"id": "x"}

        async with self.client._subscriber_lock:  # pylint: disable=protected-access
            self.client._subscribers["conv-full"] = {  # pylint: disable=protected-access
                _QueueAlwaysFull(),
                _QueueStillFull(),
            }
        await self.client._publish_event("conv-full", {"id": "2"})  # pylint: disable=protected-access

    async def test_publish_cleanup_state_and_helper_branches(self) -> None:
        # _publish_event QueueFull branch.
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
        self.keyval.put("other:key", "{}")
        self.keyval.put(self.client._media_token_key("invalid"), "not-json")  # pylint: disable=protected-access
        self.keyval.put(
            self.client._media_token_key("no-file"),  # pylint: disable=protected-access
            json.dumps({"expires_at": 9999999999, "file_path": None}),
        )
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
        no_dir_client = DefaultWebClient(
            config=_build_config(basedir=self.tmpdir.name),
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        no_dir_client._media_storage_path = os.path.join(self.tmpdir.name, "absent")  # pylint: disable=protected-access
        await no_dir_client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        # age < retention branch.
        young_client = DefaultWebClient(
            config=_build_config(basedir=self.tmpdir.name),
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        young_client._media_retention_seconds = 999999  # pylint: disable=protected-access
        young_client._media_storage_path = str(media_dir)  # pylint: disable=protected-access
        await young_client._cleanup_media_tokens_and_files()  # pylint: disable=protected-access

        # _mark_job_status continue branch and done branch.
        async with self.client._storage_lock:  # pylint: disable=protected-access
            self.client._write_queue_state_unlocked(  # pylint: disable=protected-access
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
            queue_state = self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            self.assertEqual(queue_state["jobs"][1]["status"], "done")
            self.assertIn("completed_at", queue_state["jobs"][1])

        # recover stale keeps non-processing jobs untouched.
        async with self.client._storage_lock:  # pylint: disable=protected-access
            self.client._recover_stale_processing_jobs_unlocked()  # pylint: disable=protected-access
            queue_state = self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
            queue_state["jobs"][0]["status"] = "processing"
            queue_state["jobs"][0]["lease_expires_at"] = 9999999999
            self.client._write_queue_state_unlocked(queue_state)  # pylint: disable=protected-access
            self.client._recover_stale_processing_jobs_unlocked()  # pylint: disable=protected-access

    async def test_state_and_config_helper_branches(self) -> None:
        # conversation owner branches.
        with self.assertRaises(KeyError):
            self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-x",
                auth_user="user-1",
                create_if_missing=False,
            )

        self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
            conversation_id="conv-x",
            auth_user="user-1",
            create_if_missing=True,
        )
        with self.assertRaises(PermissionError):
            self.client._ensure_conversation_owner_unlocked(  # pylint: disable=protected-access
                conversation_id="conv-x",
                auth_user="user-2",
                create_if_missing=False,
            )

        # read_queue_state jobs non-list.
        self.keyval.put(self.client._queue_state_key, json.dumps({"jobs": {}}))  # pylint: disable=protected-access
        queue = self.client._read_queue_state_unlocked()  # pylint: disable=protected-access
        self.assertEqual(queue["jobs"], [])

        # read_event_log malformed fields.
        self.keyval.put(
            self.client._event_log_key("conv-e"),  # pylint: disable=protected-access
            json.dumps({"events": {}, "next_event_id": "bad"}),
        )
        log = self.client._read_event_log_unlocked("conv-e")  # pylint: disable=protected-access
        self.assertEqual(log["events"], [])
        self.assertEqual(log["next_event_id"], 1)

        self.keyval.put(
            self.client._event_log_key("conv-e2"),  # pylint: disable=protected-access
            json.dumps({"events": [], "next_event_id": -5}),
        )
        log = self.client._read_event_log_unlocked("conv-e2")  # pylint: disable=protected-access
        self.assertEqual(log["next_event_id"], 1)

        # read_json branches.
        self.keyval.put("bytes_bad", b"\xff")
        self.assertIsNone(self.client._read_json_unlocked("bytes_bad"))  # pylint: disable=protected-access
        self.keyval.put("invalid_json", "{bad")
        self.assertIsNone(self.client._read_json_unlocked("invalid_json"))  # pylint: disable=protected-access
        self.keyval.put("scalar_json", "123")
        self.assertIsNone(self.client._read_json_unlocked("scalar_json"))  # pylint: disable=protected-access

        # resolve_allowed_mimetypes branches.
        cfg = _build_config(basedir=self.tmpdir.name)
        cfg.web.media.allowed_mimetypes = "bad"
        helper_client = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
            logging_gateway=self.logger,
            messaging_service=self.messaging,
            user_service=Mock(),
        )
        self.assertTrue(helper_client.media_allowed_mimetypes)
        cfg.web.media.allowed_mimetypes = [123, ""]
        helper_client_2 = DefaultWebClient(
            config=cfg,
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
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
        no_base_cfg = SimpleNamespace(web=SimpleNamespace(media=SimpleNamespace()))
        no_base_client = DefaultWebClient(
            config=no_base_cfg,
            ipc_service=Mock(),
            keyval_storage_gateway=_InMemoryKeyVal(),
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
        self.assertEqual(
            self.client._resolve_float_config(("web", "sse", "keepalive_seconds"), 1.0, minimum=100.0),  # pylint: disable=protected-access
            1.0,
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
        self.assertIsNone(self.client._coerce_float("x"))  # pylint: disable=protected-access

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

        with patch("builtins.open", side_effect=OSError()):
            self.assertIsNone(
                self.client._resolve_media_source_path(  # pylint: disable=protected-access
                    file_path=b"payload",
                    filename="payload.bin",
                )
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
