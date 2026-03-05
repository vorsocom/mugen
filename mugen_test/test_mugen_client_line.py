"""Unit tests for mugen.core.client.line.DefaultLineClient."""

from __future__ import annotations

import asyncio
from http import HTTPMethod
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from mugen.core.client.line import DefaultLineClient


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def iter_chunked(self, _chunk_size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int,
        text: str = "",
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status = status
        self._text = text
        self.headers = headers or {}
        self.content = _FakeStream(chunks or [])
        self.released = False
        self.closed = False

    async def text(self) -> str:
        return self._text

    def release(self) -> None:
        self.released = True

    def close(self) -> None:
        self.closed = True


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
        line=SimpleNamespace(
            channel=SimpleNamespace(
                access_token="line-token-1",
                secret="line-secret-1",
            ),
            webhook=SimpleNamespace(
                path_token="path-token-1",
                dedupe_ttl_seconds=86400,
            ),
            api=SimpleNamespace(
                base_url="https://api.line.me",
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


class TestMugenClientLine(unittest.IsolatedAsyncioTestCase):
    """Covers LINE adapter startup, retries, send mapping, and media download."""

    async def test_init_and_close_happy_path(self) -> None:
        config = _make_config()
        logger = Mock()
        session = Mock()
        session.closed = False
        session.close = AsyncMock()

        with patch(
            "mugen.core.client.line.aiohttp.ClientSession",
            return_value=session,
        ):
            client = DefaultLineClient(
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
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        existing_session = Mock()
        existing_session.closed = False
        client._client_session = existing_session  # pylint: disable=protected-access

        with patch("mugen.core.client.line.aiohttp.ClientSession") as session_cls:
            await client.init()

        session_cls.assert_not_called()

    async def test_close_handles_none_timeout_and_exception(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
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
            "mugen.core.client.line.asyncio.wait_for",
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
            "mugen.core.client.line.asyncio.wait_for",
            new=AsyncMock(side_effect=_raise_runtime),
        ):
            with self.assertRaisesRegex(RuntimeError, "close failed"):
                await client.close()

    async def test_verify_startup_success_and_failure(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
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
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        session = SimpleNamespace(
            closed=False,
            request=AsyncMock(
                return_value=_FakeResponse(
                    status=200,
                    text='{"displayName": "line-bot"}',
                )
            ),
        )
        client._client_session = session  # pylint: disable=protected-access

        success = await client._call_api(  # pylint: disable=protected-access
            path="/v2/bot/info",
            method=HTTPMethod.GET,
        )
        self.assertTrue(success["ok"])
        self.assertEqual(success["status"], 200)

        session_retry = SimpleNamespace(
            closed=False,
            request=AsyncMock(
                side_effect=[
                    _FakeResponse(status=503, text='{"message": "retry"}'),
                    _FakeResponse(status=200, text='{"displayName": "line-bot"}'),
                ]
            ),
        )
        client._client_session = session_retry  # pylint: disable=protected-access

        with patch("mugen.core.client.line.asyncio.sleep", new=AsyncMock(return_value=None)):
            retried = await client._call_api(  # pylint: disable=protected-access
                path="/v2/bot/info",
                method=HTTPMethod.GET,
            )
        self.assertTrue(retried["ok"])
        self.assertEqual(session_retry.request.await_count, 2)

        session_exception = SimpleNamespace(
            closed=False,
            request=AsyncMock(side_effect=aiohttp.ClientConnectionError("down")),
        )
        client._client_session = session_exception  # pylint: disable=protected-access
        client._max_api_retries = 0  # pylint: disable=protected-access
        failed = await client._call_api(  # pylint: disable=protected-access
            path="/v2/bot/info",
            method=HTTPMethod.GET,
        )
        self.assertFalse(failed["ok"])
        self.assertIn("ClientConnectionError", failed["error"])

        session_bad_payload = SimpleNamespace(
            closed=False,
            request=AsyncMock(return_value=_FakeResponse(status=400, text='{"message": "bad"}')),
        )
        client._client_session = session_bad_payload  # pylint: disable=protected-access
        bad = await client._call_api(  # pylint: disable=protected-access
            path="/v2/bot/info",
            method=HTTPMethod.GET,
        )
        self.assertFalse(bad["ok"])
        self.assertIn("bad", bad["error"])

        session_nondict_payload = SimpleNamespace(
            closed=False,
            request=AsyncMock(return_value=_FakeResponse(status=400, text='["bad"]')),
        )
        client._client_session = session_nondict_payload  # pylint: disable=protected-access
        nondict = await client._call_api(  # pylint: disable=protected-access
            path="/v2/bot/info",
            method=HTTPMethod.GET,
        )
        self.assertFalse(nondict["ok"])
        self.assertIsNone(nondict["data"])

    async def test_call_api_uses_init_when_session_missing(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        response = _FakeResponse(status=200, text='{"displayName": "line-bot"}')

        async def _init_client_session() -> None:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                request=AsyncMock(return_value=response),
            )

        with patch.object(
            client,
            "init",
            new=AsyncMock(side_effect=_init_client_session),
        ) as init_mock:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                request=AsyncMock(return_value=response),
            )
            await client._call_api(  # pylint: disable=protected-access
                path="/v2/bot/info",
                method=HTTPMethod.GET,
            )
            init_mock.assert_not_awaited()

            client._client_session = None  # pylint: disable=protected-access
            await client._call_api(  # pylint: disable=protected-access
                path="/v2/bot/info",
                method=HTTPMethod.GET,
            )
            init_mock.assert_awaited_once()

    async def test_message_ops_validation_and_raw_dispatch(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
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
        ) as call_api:
            ok_reply = await client.reply_messages(
                reply_token="token",
                messages=[{"type": "text", "text": "hi"}],
            )
            ok_push = await client.push_messages(
                to="U1",
                messages=[{"type": "text", "text": "hi"}],
            )
            ok_multi = await client.multicast_messages(
                to=["U1", "U2"],
                messages=[{"type": "text", "text": "hi"}],
            )

        self.assertTrue(ok_reply["ok"])
        self.assertTrue(ok_push["ok"])
        self.assertTrue(ok_multi["ok"])
        self.assertEqual(call_api.await_count, 3)

        self.assertFalse(
            (
                await client.reply_messages(
                    reply_token="",
                    messages=[{"type": "text", "text": "hi"}],
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.push_messages(
                    to="",
                    messages=[{"type": "text", "text": "hi"}],
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.multicast_messages(
                    to=[],
                    messages=[{"type": "text", "text": "hi"}],
                )
            )["ok"]
        )

        with (
            patch.object(
                client,
                "reply_messages",
                new=AsyncMock(return_value={"ok": True, "status": 200}),
            ) as reply_mock,
            patch.object(
                client,
                "push_messages",
                new=AsyncMock(return_value={"ok": True, "status": 200}),
            ) as push_mock,
            patch.object(
                client,
                "multicast_messages",
                new=AsyncMock(return_value={"ok": True, "status": 200}),
            ) as multi_mock,
        ):
            self.assertTrue(
                (
                    await client.send_raw_message(
                        op="reply",
                        payload={"reply_token": "rt", "messages": [{"type": "text", "text": "a"}]},
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_raw_message(
                        op="push",
                        payload={"to": "U1", "messages": [{"type": "text", "text": "a"}]},
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_raw_message(
                        op="multicast",
                        payload={"to": ["U1"], "messages": [{"type": "text", "text": "a"}]},
                    )
                )["ok"]
            )
            unsupported = await client.send_raw_message(op="unknown", payload={})
        reply_mock.assert_awaited_once()
        push_mock.assert_awaited_once()
        multi_mock.assert_awaited_once()
        self.assertFalse(unsupported["ok"])

    async def test_send_helpers_cover_reply_and_push_and_https_enforcement(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        with (
            patch.object(
                client,
                "reply_messages",
                new=AsyncMock(return_value={"ok": True, "status": 200}),
            ) as reply_mock,
            patch.object(
                client,
                "push_messages",
                new=AsyncMock(return_value={"ok": True, "status": 200}),
            ) as push_mock,
        ):
            self.assertTrue(
                (
                    await client.send_text_message(
                        recipient="U1",
                        text="hello",
                        reply_token="rt",
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_text_message(
                        recipient="U1",
                        text="hello",
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_image_message(
                        recipient="U1",
                        image={"url": "https://example.com/a.png"},
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_audio_message(
                        recipient="U1",
                        audio={"url": "https://example.com/a.m4a"},
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_video_message(
                        recipient="U1",
                        video={"url": "https://example.com/a.mp4"},
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_file_message(
                        recipient="U1",
                        file={"url": "https://example.com/a.txt", "name": "file.txt"},
                    )
                )["ok"]
            )

        self.assertGreaterEqual(reply_mock.await_count, 1)
        self.assertGreaterEqual(push_mock.await_count, 1)

        self.assertFalse(
            (
                await client.send_text_message(
                    recipient="U1",
                    text="",
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_image_message(
                    recipient="U1",
                    image={"url": "http://example.com/a.png"},
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_audio_message(
                    recipient="U1",
                    audio={"url": "file:///tmp/a.m4a"},
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_video_message(
                    recipient="U1",
                    video={"url": "http://example.com/a.mp4"},
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_file_message(
                    recipient="U1",
                    file={"uri": "/tmp/a.txt"},
                )
            )["ok"]
        )

    async def test_download_media_paths(self) -> None:
        logger = Mock()
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logger,
            messaging_service=Mock(),
            user_service=Mock(),
        )

        self.assertIsNone(await client.download_media(message_id=""))

        response_ok = _FakeResponse(
            status=200,
            headers={"Content-Type": "audio/ogg", "Content-Length": "4"},
            chunks=[b"ab", b"cd"],
        )
        session_ok = SimpleNamespace(closed=False, request=AsyncMock(return_value=response_ok))
        client._client_session = session_ok  # pylint: disable=protected-access
        downloaded = await client.download_media(message_id="m-1")
        self.assertIsInstance(downloaded, dict)
        self.assertTrue(os.path.isfile(downloaded["path"]))
        os.remove(downloaded["path"])

        response_bad_status = _FakeResponse(status=404, headers={"Content-Type": "audio/ogg"})
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(return_value=response_bad_status),
        )
        self.assertIsNone(await client.download_media(message_id="m-2"))

        response_bad_mime = _FakeResponse(status=200, headers={"Content-Type": "application/x-msdownload"})
        client._allowed_mimetypes = (  # pylint: disable=protected-access
            "audio/*",
            "image/*",
            "video/*",
            "text/*",
        )
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(return_value=response_bad_mime),
        )
        self.assertIsNone(await client.download_media(message_id="m-3"))

        response_too_large = _FakeResponse(
            status=200,
            headers={"Content-Type": "audio/ogg", "Content-Length": "999999"},
        )
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(return_value=response_too_large),
        )
        self.assertIsNone(await client.download_media(message_id="m-4"))

        client._max_download_bytes = 3  # pylint: disable=protected-access
        response_stream_too_large = _FakeResponse(
            status=200,
            headers={"Content-Type": "audio/ogg"},
            chunks=[b"ab", b"cd"],
        )
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(return_value=response_stream_too_large),
        )
        self.assertIsNone(await client.download_media(message_id="m-5"))

        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(side_effect=RuntimeError("boom")),
        )
        self.assertIsNone(await client.download_media(message_id="m-6"))

    async def test_download_media_init_branch_and_mime_matching(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        response = _FakeResponse(
            status=200,
            headers={"Content-Type": "audio/ogg"},
            chunks=[b"ab"],
        )

        async def _init_client_session() -> None:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                request=AsyncMock(return_value=response),
            )

        with patch.object(
            client,
            "init",
            new=AsyncMock(side_effect=_init_client_session),
        ) as init_mock:
            client._client_session = None  # pylint: disable=protected-access
            downloaded = await client.download_media(message_id="m-7")
            init_mock.assert_awaited_once()
            self.assertTrue(os.path.isfile(downloaded["path"]))
            os.remove(downloaded["path"])

        self.assertTrue(client._mime_allowed("audio/ogg"))  # pylint: disable=protected-access
        self.assertFalse(client._mime_allowed(None))  # pylint: disable=protected-access

    async def test_profile_and_processing_signal_paths(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "status": 200, "data": {"displayName": "U"}}),
        ) as call_api:
            self.assertIsNone(await client.get_profile(user_id=""))
            profile = await client.get_profile(user_id="U1")
            self.assertTrue(profile["ok"])
            call_api.assert_awaited_once()

            client._typing_enabled = False  # pylint: disable=protected-access
            self.assertIsNone(
                await client.emit_processing_signal(
                    "U1",
                    state="start",
                )
            )

        client._typing_enabled = True  # pylint: disable=protected-access
        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True, "status": 200}),
        ) as call_api:
            self.assertFalse(await client.emit_processing_signal("", state="start"))
            self.assertTrue(await client.emit_processing_signal("U1", state="stop"))
            self.assertTrue(await client.emit_processing_signal("U1", state="start"))
            call_api.assert_awaited_once()

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": False, "status": 500}),
        ):
            self.assertFalse(await client.emit_processing_signal("U1", state="start"))

    async def test_resolve_helpers(self) -> None:
        config = _make_config()
        config.line.api.base_url = " "
        config.line.channel.access_token = " token "
        config.line.media.allowed_mimetypes = ["audio/*", "", "audio/*", "image/*"]
        config.line.media.max_download_bytes = "bad"
        config.line.api.max_api_retries = -1
        config.line.api.retry_backoff_seconds = None
        config.line.typing.enabled = "off"
        client = DefaultLineClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        self.assertEqual(
            client._resolve_api_base_url(),  # pylint: disable=protected-access
            "https://api.line.me",
        )
        self.assertEqual(
            client._resolve_access_token(),  # pylint: disable=protected-access
            "token",
        )
        self.assertEqual(
            client._resolve_max_download_bytes(),  # pylint: disable=protected-access
            client._default_max_download_bytes,  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._resolve_max_api_retries(),  # pylint: disable=protected-access
            client._default_max_api_retries,  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._resolve_retry_backoff_seconds(),  # pylint: disable=protected-access
            client._default_retry_backoff_seconds,  # pylint: disable=protected-access
        )
        self.assertFalse(
            client._resolve_typing_enabled()  # pylint: disable=protected-access
        )

        self.assertIsNone(client._coerce_https_url("http://example.com"))  # pylint: disable=protected-access
        self.assertEqual(
            client._coerce_https_url("https://example.com"),  # pylint: disable=protected-access
            "https://example.com",
        )

    async def test_helper_and_validation_edge_branches(self) -> None:
        config = _make_config()
        config.line.api.timeout_seconds = None
        config.line.media.max_download_bytes = 0
        config.line.api.max_api_retries = "bad"
        config.line.media.allowed_mimetypes = "audio/*"
        client = DefaultLineClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(
            client._resolve_http_timeout_seconds(),  # pylint: disable=protected-access
            client._default_http_timeout_seconds,  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._resolve_max_download_bytes(),  # pylint: disable=protected-access
            client._default_max_download_bytes,  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._resolve_max_api_retries(),  # pylint: disable=protected-access
            client._default_max_api_retries,  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._resolve_allowed_mimetypes(),  # pylint: disable=protected-access
            client._default_allowed_mimetypes,  # pylint: disable=protected-access
        )

        config_empty_mime = _make_config()
        config_empty_mime.line.media.allowed_mimetypes = [None, "   "]
        client_empty_mime = DefaultLineClient(
            config=config_empty_mime,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(
            client_empty_mime._resolve_allowed_mimetypes(),  # pylint: disable=protected-access
            client_empty_mime._default_allowed_mimetypes,  # pylint: disable=protected-access
        )
        self.assertIsNone(
            client_empty_mime._parse_response_payload(None)  # pylint: disable=protected-access
        )
        self.assertIsNone(
            client_empty_mime._parse_response_payload("{bad-json}")  # pylint: disable=protected-access
        )
        self.assertEqual(
            client_empty_mime._resolve_correlation_id("cid-1"),  # pylint: disable=protected-access
            "cid-1",
        )
        self.assertIn(
            "boom",
            client_empty_mime._response_error_text(  # pylint: disable=protected-access
                {"message": "boom", "details": ["d1"]},
                fallback="fallback",
            ),
        )
        self.assertEqual(
            client_empty_mime._response_error_text(  # pylint: disable=protected-access
                {"message": " "},
                fallback="fallback",
            ),
            "fallback",
        )
        self.assertIsNone(client_empty_mime._coerce_https_url("   "))  # pylint: disable=protected-access

        client_empty_mime._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=True
        )
        await client_empty_mime.close()
        self.assertIsNone(client_empty_mime._client_session)  # pylint: disable=protected-access

        self.assertFalse(
            (
                await client_empty_mime.reply_messages(
                    reply_token="rt",
                    messages=[],
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client_empty_mime.push_messages(
                    to="U1",
                    messages=[],
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client_empty_mime.multicast_messages(
                    to=["", "  "],
                    messages=[{"type": "text", "text": "x"}],
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client_empty_mime.multicast_messages(
                    to=["U1"],
                    messages=[],
                )
            )["ok"]
        )

    async def test_send_and_raw_validation_edge_branches(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        with (
            patch.object(
                client,
                "reply_messages",
                new=AsyncMock(return_value={"ok": True, "status": 200}),
            ) as reply_mock,
            patch.object(
                client,
                "push_messages",
                new=AsyncMock(return_value={"ok": True, "status": 200}),
            ) as push_mock,
            patch.object(
                client,
                "send_text_message",
                new=AsyncMock(return_value={"ok": True, "status": 200}),
            ) as text_mock,
        ):
            self.assertTrue(
                (
                    await client.send_image_message(
                        recipient="U1",
                        image={
                            "original_content_url": "https://example.com/image.png",
                            "preview_image_url": "https://example.com/preview.png",
                        },
                        reply_token="rt",
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_image_message(
                        recipient="U1",
                        image={
                            "url": "https://example.com/image2.png",
                            "preview_url": "https://example.com/preview2.png",
                        },
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_audio_message(
                        recipient="U1",
                        audio={
                            "original_content_url": "https://example.com/audio.m4a",
                            "duration": 1234,
                        },
                        reply_token="rt",
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_video_message(
                        recipient="U1",
                        video={
                            "original_content_url": "https://example.com/video.mp4",
                            "preview_image_url": "https://example.com/video_preview.png",
                        },
                        reply_token="rt",
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_video_message(
                        recipient="U1",
                        video={
                            "url": "https://example.com/video2.mp4",
                            "preview_url": "https://example.com/video2_preview.png",
                        },
                    )
                )["ok"]
            )
            self.assertTrue(
                (
                    await client.send_file_message(
                        recipient="U1",
                        file={"uri": "https://example.com/file.txt"},
                    )
                )["ok"]
            )

        self.assertEqual(reply_mock.await_count, 3)
        self.assertEqual(push_mock.await_count, 2)
        text_mock.assert_awaited_once_with(
            recipient="U1",
            text="https://example.com/file.txt",
            reply_token=None,
        )

        self.assertFalse(
            (
                await client.send_raw_message(
                    op="reply",
                    payload={"messages": [{"type": "text", "text": "x"}]},
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_raw_message(
                    op="reply",
                    payload={"reply_token": "rt", "messages": "bad"},
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_raw_message(
                    op="push",
                    payload={"messages": [{"type": "text", "text": "x"}]},
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_raw_message(
                    op="push",
                    payload={"to": "U1", "messages": "bad"},
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_raw_message(
                    op="multicast",
                    payload={"to": "U1", "messages": [{"type": "text", "text": "x"}]},
                )
            )["ok"]
        )
        self.assertFalse(
            (
                await client.send_raw_message(
                    op="multicast",
                    payload={"to": ["U1"], "messages": "bad"},
                )
            )["ok"]
        )

    async def test_call_api_edge_branches(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(side_effect=asyncio.CancelledError()),
        )
        with self.assertRaises(asyncio.CancelledError):
            await client._call_api(  # pylint: disable=protected-access
                path="/v2/bot/info",
                method=HTTPMethod.GET,
            )

        client._max_api_retries = 1  # pylint: disable=protected-access
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(
                side_effect=[
                    aiohttp.ClientConnectionError("down-1"),
                    aiohttp.ClientConnectionError("down-2"),
                ]
            ),
        )
        with patch.object(
            client,
            "_wait_before_retry",
            new=AsyncMock(return_value=None),
        ) as wait_mock:
            failed = await client._call_api(  # pylint: disable=protected-access
                path="/v2/bot/info",
                method=HTTPMethod.GET,
                correlation_id="cid-1",
            )
        self.assertFalse(failed["ok"])
        wait_mock.assert_awaited_once()

        client._max_api_retries = -1  # pylint: disable=protected-access
        exhausted = await client._call_api(  # pylint: disable=protected-access
            path="/v2/bot/info",
            method=HTTPMethod.GET,
        )
        self.assertFalse(exhausted["ok"])
        self.assertIn("exhausted retries", exhausted["error"])

    async def test_download_media_edge_branches(self) -> None:
        client = DefaultLineClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        response_invalid_len = _FakeResponse(
            status=200,
            headers={"Content-Type": "audio/ogg", "Content-Length": "not-a-number"},
            chunks=[b"ab"],
        )
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(return_value=response_invalid_len),
        )
        downloaded = await client.download_media(message_id="m-edge-1")
        self.assertIsInstance(downloaded, dict)
        os.remove(downloaded["path"])

        response_open_fail = _FakeResponse(
            status=200,
            headers={"Content-Type": "audio/ogg"},
            chunks=[b"ab"],
        )
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(return_value=response_open_fail),
        )
        with (
            patch("mugen.core.client.line.open", side_effect=RuntimeError("write failed")),
            patch("mugen.core.client.line.os.remove", side_effect=OSError("remove failed")),
        ):
            self.assertIsNone(await client.download_media(message_id="m-edge-2"))

        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            request=AsyncMock(side_effect=asyncio.CancelledError()),
        )
        with self.assertRaises(asyncio.CancelledError):
            await client.download_media(message_id="m-edge-3")
