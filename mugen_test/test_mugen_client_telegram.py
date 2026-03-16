"""Unit tests for mugen.core.client.telegram.DefaultTelegramClient."""

from __future__ import annotations

import asyncio
from http import HTTPMethod
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.client.telegram import DefaultTelegramClient


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int,
        text: str = "",
        blob: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._text = text
        self._blob = blob
        self.headers = headers or {}

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._blob


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            runtime=SimpleNamespace(
                profile="platform_full",
                provider_readiness_timeout_seconds=15.0,
                provider_shutdown_timeout_seconds=10.0,
                shutdown_timeout_seconds=60.0,
                phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
            )
        ),
        telegram=SimpleNamespace(
            bot=SimpleNamespace(token="token-123"),
            webhook=SimpleNamespace(
                path_token="path-1",
                secret_token="secret-1",
                dedupe_ttl_seconds=86400,
            ),
            api=SimpleNamespace(
                base_url="https://api.telegram.org",
                timeout_seconds=10.0,
                max_api_retries=2,
                retry_backoff_seconds=0.1,
            ),
            media=SimpleNamespace(
                allowed_mimetypes=[
                    "audio/*",
                    "image/*",
                    "video/*",
                    "application/*",
                    "text/*",
                ],
                max_download_bytes=1024,
            ),
            typing=SimpleNamespace(enabled=True),
        ),
    )


class TestMugenClientTelegram(unittest.IsolatedAsyncioTestCase):
    """Covers Telegram adapter startup, retries, send mapping, and media download."""

    async def test_init_and_close_happy_path(self) -> None:
        config = _make_config()
        logger = Mock()
        session = Mock()
        session.closed = False
        session.close = AsyncMock()

        with patch(
            "mugen.core.client.telegram.aiohttp.ClientSession",
            return_value=session,
        ):
            client = DefaultTelegramClient(
                config=config,
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=logger,
                messaging_service=Mock(),
                user_service=Mock(),
            )
            await client.init()
            await client.close()

        session.close.assert_awaited_once()

    async def test_init_is_idempotent_when_session_open(self) -> None:
        config = _make_config()
        logger = Mock()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logger,
            messaging_service=Mock(),
            user_service=Mock(),
        )
        existing_session = Mock()
        existing_session.closed = False
        client._client_session = existing_session  # pylint: disable=protected-access

        with patch("mugen.core.client.telegram.aiohttp.ClientSession") as session_cls:
            await client.init()

        session_cls.assert_not_called()

    async def test_close_handles_none_timeout_and_exception(self) -> None:
        config = _make_config()
        logger = Mock()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logger,
            messaging_service=Mock(),
            user_service=Mock(),
        )

        await client.close()

        session_timeout = Mock()
        session_timeout.closed = False
        session_timeout.close = AsyncMock()
        client._client_session = session_timeout  # pylint: disable=protected-access

        async def _raise_timeout(awaitable, *_args, **_kwargs):
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise asyncio.TimeoutError

        with patch(
            "mugen.core.client.telegram.asyncio.wait_for",
            new=AsyncMock(side_effect=_raise_timeout),
        ):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                await client.close()

        session_error = Mock()
        session_error.closed = False
        session_error.close = AsyncMock()
        client._client_session = session_error  # pylint: disable=protected-access

        async def _raise_runtime(awaitable, *_args, **_kwargs):
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise RuntimeError("boom")

        with patch(
            "mugen.core.client.telegram.asyncio.wait_for",
            new=AsyncMock(side_effect=_raise_runtime),
        ):
            with self.assertRaisesRegex(RuntimeError, "close failed"):
                await client.close()

    async def test_verify_startup_success_and_failure(self) -> None:
        config = _make_config()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "status": 200}),
        ):
            self.assertTrue(await client.verify_startup())

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": False, "status": 500, "error": "bad"}),
        ):
            self.assertFalse(await client.verify_startup())

    async def test_call_api_success_retry_and_errors(self) -> None:
        config = _make_config()
        logger = Mock()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logger,
            messaging_service=Mock(),
            user_service=Mock(),
        )

        session = SimpleNamespace(
            closed=False,
            get=AsyncMock(
                return_value=_FakeResponse(
                    status=200,
                    text='{"ok": true, "result": {"id": 1}}',
                )
            ),
            post=AsyncMock(),
        )
        client._client_session = session  # pylint: disable=protected-access

        success = await client._call_api(  # pylint: disable=protected-access
            "getMe",
            method=HTTPMethod.GET,
        )
        self.assertTrue(success["ok"])

        session_retry = SimpleNamespace(
            closed=False,
            post=AsyncMock(
                side_effect=[
                    _FakeResponse(status=503, text='{"ok": false, "description": "retry"}'),
                    _FakeResponse(status=200, text='{"ok": true, "result": {"id": 1}}'),
                ]
            ),
            get=AsyncMock(),
        )
        client._client_session = session_retry  # pylint: disable=protected-access

        with patch("mugen.core.client.telegram.asyncio.sleep", new=AsyncMock(return_value=None)):
            retried = await client._call_api(  # pylint: disable=protected-access
                "sendMessage",
                payload={"chat_id": "1", "text": "hi"},
            )
        self.assertTrue(retried["ok"])
        self.assertEqual(session_retry.post.await_count, 2)

        session_exception = SimpleNamespace(
            closed=False,
            post=AsyncMock(side_effect=RuntimeError("down")),
            get=AsyncMock(),
        )
        client._client_session = session_exception  # pylint: disable=protected-access
        client._max_api_retries = 0  # pylint: disable=protected-access
        failed = await client._call_api("sendMessage", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(failed["ok"])
        self.assertIn("request error", failed["error"])

        session_bad_payload = SimpleNamespace(
            closed=False,
            post=AsyncMock(return_value=_FakeResponse(status=400, text='{"ok": false}')),
            get=AsyncMock(),
        )
        client._client_session = session_bad_payload  # pylint: disable=protected-access
        bad = await client._call_api("sendMessage", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(bad["ok"])
        self.assertIn("failed", bad["error"])

        session_nondict_payload = SimpleNamespace(
            closed=False,
            post=AsyncMock(return_value=_FakeResponse(status=400, text='["bad"]')),
            get=AsyncMock(),
        )
        client._client_session = session_nondict_payload  # pylint: disable=protected-access
        nondict = await client._call_api("sendMessage", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(nondict["ok"])
        self.assertIsNone(nondict["data"])

    async def test_call_api_uses_init_when_session_missing(self) -> None:
        config = _make_config()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        response = _FakeResponse(status=200, text='{"ok": true, "result": {}}')

        async def _init_client_session() -> None:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                post=AsyncMock(return_value=response),
                get=AsyncMock(return_value=response),
            )

        with patch.object(
            client,
            "init",
            new=AsyncMock(side_effect=_init_client_session),
        ) as init_mock:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                post=AsyncMock(return_value=response),
                get=AsyncMock(return_value=response),
            )
            await client._call_api("sendMessage", payload={"chat_id": "1", "text": "ok"})  # pylint: disable=protected-access
            init_mock.assert_not_awaited()

            client._client_session = None  # pylint: disable=protected-access
            await client._call_api("sendMessage", payload={"chat_id": "1", "text": "ok"})  # pylint: disable=protected-access
            init_mock.assert_awaited_once()

    async def test_call_api_with_file_paths(self) -> None:
        config = _make_config()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        invalid = await client._call_api_with_file(  # pylint: disable=protected-access
            "sendDocument",
            file_field="document",
            file_path="",
            payload_fields={},
        )
        self.assertFalse(invalid["ok"])

        missing = await client._call_api_with_file(  # pylint: disable=protected-access
            "sendDocument",
            file_field="document",
            file_path="/tmp/does-not-exist",
            payload_fields={},
        )
        self.assertFalse(missing["ok"])

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"data")
            file_path = handle.name

        try:
            session = SimpleNamespace(
                closed=False,
                post=AsyncMock(
                    return_value=_FakeResponse(
                        status=200,
                        text='{"ok": true, "result": {"id": 1}}',
                    )
                ),
            )
            client._client_session = session  # pylint: disable=protected-access
            ok = await client._call_api_with_file(  # pylint: disable=protected-access
                "sendDocument",
                file_field="document",
                file_path=file_path,
                payload_fields={"chat_id": "1", "flag": True, "skip": None},
            )
            self.assertTrue(ok["ok"])

            session_retry = SimpleNamespace(
                closed=False,
                post=AsyncMock(
                    side_effect=[
                        _FakeResponse(status=503, text='{"ok": false, "description": "retry"}'),
                        _FakeResponse(status=200, text='{"ok": true, "result": {"id": 2}}'),
                    ]
                ),
            )
            client._client_session = session_retry  # pylint: disable=protected-access
            with patch("mugen.core.client.telegram.asyncio.sleep", new=AsyncMock(return_value=None)):
                retried = await client._call_api_with_file(  # pylint: disable=protected-access
                    "sendDocument",
                    file_field="document",
                    file_path=file_path,
                    payload_fields={"chat_id": "1"},
                )
            self.assertTrue(retried["ok"])
            self.assertEqual(session_retry.post.await_count, 2)
        finally:
            try:
                os.remove(file_path)
            except Exception:  # pylint: disable=broad-exception-caught
                ...

    async def test_media_source_and_send_method_mapping(self) -> None:
        config = _make_config()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        self.assertEqual(
            client._resolve_media_source({"id": "f1"}),  # pylint: disable=protected-access
            ("remote", "f1"),
        )
        self.assertEqual(
            client._resolve_media_source({"file_id": "f2"}),  # pylint: disable=protected-access
            ("remote", "f2"),
        )
        self.assertEqual(
            client._resolve_media_source({"uri": "/tmp/a.bin"}),  # pylint: disable=protected-access
            ("local", "/tmp/a.bin"),
        )
        with self.assertRaises(ValueError):
            client._resolve_media_source({})  # pylint: disable=protected-access

        with patch.object(client, "_call_api", new=AsyncMock(return_value={"ok": True})) as call_api:
            await client.send_text_message(chat_id="1", text="hello")
            call_api.assert_awaited_once()

        with patch.object(
            client,
            "_send_media_message",
            new=AsyncMock(return_value={"ok": True}),
        ) as send_media:
            await client.send_audio_message(chat_id="1", audio={"id": "a1"})
            await client.send_file_message(chat_id="1", document={"id": "d1"})
            await client.send_image_message(chat_id="1", photo={"id": "p1"})
            await client.send_video_message(chat_id="1", video={"id": "v1"})
        self.assertEqual(send_media.await_count, 4)

        with patch.object(client, "_call_api", new=AsyncMock(return_value={"ok": True})) as call_api:
            await client.answer_callback_query(callback_query_id="cq1", text="ok", show_alert=True)
            call_api.assert_awaited_once()

    async def test_emit_processing_signal_paths(self) -> None:
        config = _make_config()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        client._typing_enabled = False  # pylint: disable=protected-access
        self.assertTrue(await client.emit_processing_signal("1", state="start"))

        client._typing_enabled = True  # pylint: disable=protected-access
        self.assertTrue(await client.emit_processing_signal("1", state="stop"))

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True}),
        ):
            self.assertTrue(await client.emit_processing_signal("1", state="start"))

    async def test_extract_result_and_mime_helper_paths(self) -> None:
        config = _make_config()
        logger = Mock()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logger,
            messaging_service=Mock(),
            user_service=Mock(),
        )

        self.assertFalse(client._mime_allowed(""))  # pylint: disable=protected-access
        self.assertTrue(client._mime_allowed("image/png"))  # pylint: disable=protected-access

        self.assertIsNone(client._extract_result(None, "ctx"))  # pylint: disable=protected-access
        self.assertIsNone(client._extract_result("bad", "ctx"))  # pylint: disable=protected-access
        self.assertIsNone(
            client._extract_result(  # pylint: disable=protected-access
                {"ok": False, "error": "x", "raw": "raw"},
                "ctx",
            )
        )
        self.assertEqual(
            client._extract_result({"ok": True, "data": None}, "ctx"),  # pylint: disable=protected-access
            {},
        )
        self.assertIsNone(
            client._extract_result({"ok": True, "data": []}, "ctx")  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._extract_result({"ok": True, "data": {}}, "ctx"),  # pylint: disable=protected-access
            {},
        )
        self.assertIsNone(
            client._extract_result({"ok": True, "data": {"result": []}}, "ctx")  # pylint: disable=protected-access
        )

    async def test_download_media_paths(self) -> None:
        config = _make_config()
        logger = Mock()
        client = DefaultTelegramClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logger,
            messaging_service=Mock(),
            user_service=Mock(),
        )

        self.assertIsNone(await client.download_media(""))

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value=None),
        ):
            self.assertIsNone(await client.download_media("f1"))

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "data": {"result": {}}}),
        ):
            self.assertIsNone(await client.download_media("f1"))

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "data": {"result": {"file_path": "a.bin", "file_size": 9999}},
                }
            ),
        ):
            self.assertIsNone(await client.download_media("f1"))

        session_status_fail = SimpleNamespace(
            closed=False,
            get=AsyncMock(return_value=_FakeResponse(status=500)),
        )
        client._client_session = session_status_fail  # pylint: disable=protected-access
        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "data": {"result": {"file_path": "a.bin"}}}),
        ):
            self.assertIsNone(await client.download_media("f1"))

        session_blob_big = SimpleNamespace(
            closed=False,
            get=AsyncMock(
                return_value=_FakeResponse(
                    status=200,
                    blob=b"x" * 2048,
                    headers={"Content-Type": "application/octet-stream"},
                )
            ),
        )
        client._client_session = session_blob_big  # pylint: disable=protected-access
        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "data": {"result": {"file_path": "a.bin"}}}),
        ):
            self.assertIsNone(await client.download_media("f1"))

        session_bad_mime = SimpleNamespace(
            closed=False,
            get=AsyncMock(
                return_value=_FakeResponse(
                    status=200,
                    blob=b"ok",
                    headers={"Content-Type": "application/x-msdownload"},
                )
            ),
        )
        client._client_session = session_bad_mime  # pylint: disable=protected-access
        previous_mime_allowlist = client._allowed_mimetypes  # pylint: disable=protected-access
        client._allowed_mimetypes = ("image/*",)  # pylint: disable=protected-access
        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "data": {"result": {"file_path": "a.bin"}}}),
        ):
            self.assertIsNone(await client.download_media("f1"))
        client._allowed_mimetypes = previous_mime_allowlist  # pylint: disable=protected-access

        session_success = SimpleNamespace(
            closed=False,
            get=AsyncMock(
                return_value=_FakeResponse(
                    status=200,
                    blob=b"ok",
                    headers={"Content-Type": "image/png"},
                )
            ),
        )
        client._client_session = session_success  # pylint: disable=protected-access
        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "data": {"result": {"file_path": "photo.png"}}}),
        ):
            media = await client.download_media("f1")
        self.assertIsInstance(media, dict)
        self.assertEqual(media["mime_type"], "image/png")

        session_guess_mime = SimpleNamespace(
            closed=False,
            get=AsyncMock(
                return_value=_FakeResponse(
                    status=200,
                    blob=b"ok",
                    headers={},
                )
            ),
        )
        client._client_session = session_guess_mime  # pylint: disable=protected-access
        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "data": {"result": {"file_path": "note.txt"}}}),
        ):
            media_guess = await client.download_media("f2")
        self.assertIsInstance(media_guess, dict)

        session_exception = SimpleNamespace(
            closed=False,
            get=AsyncMock(side_effect=RuntimeError("boom")),
        )
        client._client_session = session_exception  # pylint: disable=protected-access
        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "data": {"result": {"file_path": "x.bin"}}}),
        ):
            self.assertIsNone(await client.download_media("f3"))

    async def test_resolver_and_payload_parser_edge_cases(self) -> None:
        bad_config = _make_config()
        bad_config.telegram.api.base_url = ""
        bad_config.telegram.api.timeout_seconds = None
        bad_config.telegram.api.max_api_retries = "invalid"
        bad_config.telegram.media.max_download_bytes = "invalid"
        bad_config.telegram.media.allowed_mimetypes = "invalid"
        client = DefaultTelegramClient(
            config=bad_config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(client._api_base_url, "https://api.telegram.org")  # pylint: disable=protected-access
        self.assertEqual(client._http_timeout_seconds, 10.0)  # pylint: disable=protected-access
        self.assertEqual(client._max_api_retries, 2)  # pylint: disable=protected-access
        self.assertEqual(client._max_download_bytes, 20 * 1024 * 1024)  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            client._allowed_mimetypes,
            ("audio/*", "image/*", "video/*", "application/*", "text/*"),
        )

        negative_config = _make_config()
        negative_config.telegram.media.max_download_bytes = -1
        negative_config.telegram.api.max_api_retries = -1
        client_negative = DefaultTelegramClient(
            config=negative_config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(client_negative._max_download_bytes, 20 * 1024 * 1024)  # pylint: disable=protected-access
        self.assertEqual(client_negative._max_api_retries, 2)  # pylint: disable=protected-access

        normalized_config = _make_config()
        normalized_config.telegram.media.allowed_mimetypes = [1, " ", "IMAGE/*", "image/*"]
        client_normalized = DefaultTelegramClient(
            config=normalized_config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(client_normalized._allowed_mimetypes, ("image/*",))  # pylint: disable=protected-access

        empty_allowlist_config = _make_config()
        empty_allowlist_config.telegram.media.allowed_mimetypes = [1, ""]
        client_empty_allowlist = DefaultTelegramClient(
            config=empty_allowlist_config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(  # pylint: disable=protected-access
            client_empty_allowlist._allowed_mimetypes,
            ("audio/*", "image/*", "video/*", "application/*", "text/*"),
        )

        self.assertIsNone(DefaultTelegramClient._parse_response_payload(None))
        self.assertIsNone(DefaultTelegramClient._parse_response_payload(""))
        self.assertIsNone(DefaultTelegramClient._parse_response_payload("not-json"))
        self.assertIsNone(DefaultTelegramClient._parse_response_payload("[]"))

    async def test_close_when_session_already_closed(self) -> None:
        client = DefaultTelegramClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        closed_session = Mock()
        closed_session.closed = True
        closed_session.close = AsyncMock()
        client._client_session = closed_session  # pylint: disable=protected-access

        await client.close()

        closed_session.close.assert_not_called()
        self.assertIsNone(client._client_session)  # pylint: disable=protected-access

    async def test_call_api_exception_retry_and_exhausted_loop_fallback(self) -> None:
        client = DefaultTelegramClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        retry_session = SimpleNamespace(
            closed=False,
            post=AsyncMock(
                side_effect=[
                    RuntimeError("temporary"),
                    _FakeResponse(
                        status=200,
                        text='{"ok": true, "result": {"id": 9}}',
                    ),
                ]
            ),
            get=AsyncMock(),
        )
        client._client_session = retry_session  # pylint: disable=protected-access
        client._max_api_retries = 1  # pylint: disable=protected-access
        with patch.object(client, "_wait_before_retry", new=AsyncMock()) as wait_retry:
            response = await client._call_api("sendMessage", payload={"chat_id": "1"})  # pylint: disable=protected-access
        self.assertTrue(response["ok"])
        wait_retry.assert_awaited_once()

        exhausted_client = DefaultTelegramClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        exhausted_client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            post=AsyncMock(),
            get=AsyncMock(),
        )
        exhausted_client._max_api_retries = -1  # pylint: disable=protected-access
        exhausted = await exhausted_client._call_api("sendMessage", payload={"chat_id": "1"})  # pylint: disable=protected-access
        self.assertFalse(exhausted["ok"])
        self.assertIn("exhausted retries", exhausted["error"])

    async def test_call_api_with_file_retry_and_error_branches(self) -> None:
        client = DefaultTelegramClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"data")
            file_path = handle.name

        try:
            retry_session = SimpleNamespace(
                closed=False,
                post=AsyncMock(
                    side_effect=[
                        RuntimeError("temporary"),
                        RuntimeError("still-down"),
                    ]
                ),
            )
            client._client_session = retry_session  # pylint: disable=protected-access
            client._max_api_retries = 1  # pylint: disable=protected-access
            with patch.object(client, "_wait_before_retry", new=AsyncMock()) as wait_retry:
                errored = await client._call_api_with_file(  # pylint: disable=protected-access
                    "sendDocument",
                    file_field="document",
                    file_path=file_path,
                    payload_fields={"chat_id": "1"},
                )
            self.assertFalse(errored["ok"])
            self.assertIn("request error", errored["error"])
            wait_retry.assert_awaited_once()

            description_fallback_session = SimpleNamespace(
                closed=False,
                post=AsyncMock(
                    return_value=_FakeResponse(
                        status=400,
                        text='{"ok": false, "description": ""}',
                    )
                ),
            )
            client._client_session = description_fallback_session  # pylint: disable=protected-access
            fallback = await client._call_api_with_file(  # pylint: disable=protected-access
                "sendDocument",
                file_field="document",
                file_path=file_path,
                payload_fields={"chat_id": "1"},
            )
            self.assertFalse(fallback["ok"])
            self.assertIn("failed for sendDocument", fallback["error"])

            nondict_payload_session = SimpleNamespace(
                closed=False,
                post=AsyncMock(
                    return_value=_FakeResponse(
                        status=400,
                        text='["bad"]',
                    )
                ),
            )
            client._client_session = nondict_payload_session  # pylint: disable=protected-access
            nondict = await client._call_api_with_file(  # pylint: disable=protected-access
                "sendDocument",
                file_field="document",
                file_path=file_path,
                payload_fields={"chat_id": "1"},
            )
            self.assertFalse(nondict["ok"])
            self.assertIsNone(nondict["data"])

            exhausted_client = DefaultTelegramClient(
                config=_make_config(),
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
                messaging_service=Mock(),
                user_service=Mock(),
            )
            exhausted_client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                post=AsyncMock(),
            )
            exhausted_client._max_api_retries = -1  # pylint: disable=protected-access
            exhausted = await exhausted_client._call_api_with_file(  # pylint: disable=protected-access
                "sendDocument",
                file_field="document",
                file_path=file_path,
                payload_fields={"chat_id": "1"},
            )
            self.assertFalse(exhausted["ok"])
            self.assertIn("exhausted retries", exhausted["error"])
        finally:
            try:
                os.remove(file_path)
            except Exception:  # pylint: disable=broad-exception-caught
                ...

    async def test_send_media_and_answer_callback_branch_variants(self) -> None:
        client = DefaultTelegramClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(
            client._resolve_media_source({"path": "/tmp/file.bin"}),  # pylint: disable=protected-access
            ("local", "/tmp/file.bin"),
        )

        with (
            patch.object(client, "_call_api", new=AsyncMock(return_value={"ok": True})) as call_api,
            patch.object(
                client,
                "_call_api_with_file",
                new=AsyncMock(return_value={"ok": True}),
            ) as call_api_with_file,
        ):
            await client._send_media_message(  # pylint: disable=protected-access
                endpoint="sendPhoto",
                field_name="photo",
                media={"id": "remote-id", "caption": "caption"},
                chat_id="1",
                reply_to_message_id=10,
            )
            await client._send_media_message(  # pylint: disable=protected-access
                endpoint="sendPhoto",
                field_name="photo",
                media={"path": "/tmp/photo.png"},
                chat_id="1",
            )
        call_api.assert_awaited_once()
        call_api_with_file.assert_awaited_once()

        with patch.object(client, "_call_api", new=AsyncMock(return_value={"ok": True})) as call_api:
            await client.send_text_message(
                chat_id="1",
                text="hello",
                reply_markup={"inline_keyboard": []},
                reply_to_message_id=99,
            )
        sent_payload = call_api.await_args.kwargs["payload"]
        self.assertIn("reply_markup", sent_payload)
        self.assertEqual(sent_payload["reply_to_message_id"], 99)

        with patch.object(client, "_call_api", new=AsyncMock(return_value={"ok": True})) as call_api:
            await client.answer_callback_query(
                callback_query_id="cq-1",
                text=None,
                show_alert="yes",
            )
        callback_payload = call_api.await_args.kwargs["payload"]
        self.assertEqual(callback_payload, {"callback_query_id": "cq-1"})

    async def test_extract_result_error_branch_and_download_init_path(self) -> None:
        logger = Mock()
        client = DefaultTelegramClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logger,
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertIsNone(
            client._extract_result(  # pylint: disable=protected-access
                {"ok": False, "error": "", "raw": ""},
                "ctx",
            )
        )

        async def _init_session() -> None:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                get=AsyncMock(
                    return_value=_FakeResponse(
                        status=200,
                        blob=b"ok",
                        headers={"Content-Type": "image/png"},
                    )
                ),
            )

        client._client_session = None  # pylint: disable=protected-access
        with (
            patch.object(client, "init", new=AsyncMock(side_effect=_init_session)) as init_mock,
            patch.object(
                client,
                "_call_api",
                new=AsyncMock(
                    return_value={"ok": True, "data": {"result": {"file_path": "photo.png"}}}
                ),
            ),
        ):
            media = await client.download_media("media-1")
        self.assertIsInstance(media, dict)
        init_mock.assert_awaited_once()
