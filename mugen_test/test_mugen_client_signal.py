"""Unit tests for mugen.core.client.signal.DefaultSignalClient."""

from __future__ import annotations

import asyncio
from http import HTTPMethod
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from mugen.core.client.signal import DefaultSignalClient


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


class _FakeWSMessage:
    def __init__(self, *, msg_type, data: object = None) -> None:
        self.type = msg_type
        self.data = data


class _FakeWebSocket:
    def __init__(self, messages: list[_FakeWSMessage], *, error: Exception | None = None) -> None:
        self._messages = list(messages)
        self._index = 0
        self._error = error

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        message = self._messages[self._index]
        self._index += 1
        return message

    def exception(self) -> Exception | None:
        return self._error


class _FakeWSContext:
    def __init__(self, websocket: _FakeWebSocket) -> None:
        self._websocket = websocket

    async def __aenter__(self) -> _FakeWebSocket:
        return self._websocket

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)
        return None


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
        signal=SimpleNamespace(
            account=SimpleNamespace(number="+15550000001"),
            api=SimpleNamespace(
                base_url="http://127.0.0.1:8080",
                bearer_token="TOKEN_1",
                timeout_seconds=10.0,
                max_api_retries=2,
                retry_backoff_seconds=0.1,
            ),
            receive=SimpleNamespace(
                heartbeat_seconds=30.0,
                reconnect_base_seconds=1.0,
                reconnect_max_seconds=30.0,
                reconnect_jitter_seconds=0.25,
                dedupe_ttl_seconds=86400,
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


class TestMugenClientSignal(unittest.IsolatedAsyncioTestCase):
    """Covers Signal adapter startup, retries, send mapping, and media download."""

    async def test_init_and_close_happy_path(self) -> None:
        config = _make_config()
        logger = Mock()
        session = Mock()
        session.closed = False
        session.close = AsyncMock()

        with patch(
            "mugen.core.client.signal.aiohttp.ClientSession",
            return_value=session,
        ):
            client = DefaultSignalClient(
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
        client = DefaultSignalClient(
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

        with patch("mugen.core.client.signal.aiohttp.ClientSession") as session_cls:
            await client.init()

        session_cls.assert_not_called()

    async def test_close_handles_none_timeout_and_exception(self) -> None:
        client = DefaultSignalClient(
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
            "mugen.core.client.signal.asyncio.wait_for",
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
            "mugen.core.client.signal.asyncio.wait_for",
            new=AsyncMock(side_effect=_raise_runtime),
        ):
            with self.assertRaisesRegex(RuntimeError, "shutdown failed"):
                await client.close()

        session_closed = Mock()
        session_closed.closed = True
        session_closed.close = AsyncMock()
        client._client_session = session_closed  # pylint: disable=protected-access
        await client.close()
        session_closed.close.assert_not_called()

    async def test_helper_paths(self) -> None:
        client = DefaultSignalClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        self.assertIsNone(client._parse_response_payload(None))  # pylint: disable=protected-access
        self.assertIsNone(client._parse_response_payload("bad"))  # pylint: disable=protected-access
        self.assertIsNone(client._parse_response_payload("1"))  # pylint: disable=protected-access
        self.assertEqual(
            client._parse_response_payload('{"ok": true}'),  # pylint: disable=protected-access
            {"ok": True},
        )
        self.assertEqual(
            client._build_api_response(ok=True, status=200)["ok"],  # pylint: disable=protected-access
            True,
        )
        self.assertTrue(client._is_retryable_status(429))  # pylint: disable=protected-access
        self.assertTrue(client._is_retryable_status(503))  # pylint: disable=protected-access
        self.assertFalse(client._is_retryable_status(400))  # pylint: disable=protected-access
        self.assertIsNotNone(client._new_correlation_id())  # pylint: disable=protected-access
        self.assertEqual(
            client._auth_headers()["Authorization"],  # pylint: disable=protected-access
            "Bearer TOKEN_1",
        )
        self.assertIsNone(client._normalize_recipient("  "))  # pylint: disable=protected-access
        self.assertEqual(
            client._normalize_recipient(" +1555 "),  # pylint: disable=protected-access
            "+1555",
        )
        self.assertIsNone(client._normalize_recipient(123))  # pylint: disable=protected-access
        self.assertTrue(client._mime_type_allowed("image/png"))  # pylint: disable=protected-access
        self.assertFalse(client._mime_type_allowed("model/gltf+json"))  # pylint: disable=protected-access

    async def test_call_api_success_retry_and_errors(self) -> None:
        client = DefaultSignalClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        session = SimpleNamespace(
            closed=False,
            get=AsyncMock(
                return_value=_FakeResponse(
                    status=200,
                    text='{"ok": true, "mode": "json-rpc"}',
                )
            ),
            post=AsyncMock(),
            delete=AsyncMock(),
            put=AsyncMock(),
        )
        client._client_session = session  # pylint: disable=protected-access

        success = await client._call_api(  # pylint: disable=protected-access
            "/v1/about",
            method=HTTPMethod.GET,
        )
        self.assertTrue(success["ok"])

        session_retry = SimpleNamespace(
            closed=False,
            get=AsyncMock(),
            post=AsyncMock(
                side_effect=[
                    _FakeResponse(status=503, text='{"error":"retry"}'),
                    _FakeResponse(status=200, text='{"ok": true, "id": 1}'),
                ]
            ),
            delete=AsyncMock(),
            put=AsyncMock(),
        )
        client._client_session = session_retry  # pylint: disable=protected-access

        with patch("mugen.core.client.signal.asyncio.sleep", new=AsyncMock(return_value=None)):
            retried = await client._call_api(  # pylint: disable=protected-access
                "/v2/send",
                payload={"message": "hi"},
            )
        self.assertTrue(retried["ok"])
        self.assertEqual(session_retry.post.await_count, 2)

        session_bad = SimpleNamespace(
            closed=False,
            get=AsyncMock(),
            post=AsyncMock(return_value=_FakeResponse(status=400, text='{"error":"bad"}')),
            delete=AsyncMock(),
            put=AsyncMock(),
        )
        client._client_session = session_bad  # pylint: disable=protected-access
        bad = await client._call_api("/v2/send", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"], "bad")

        session_fallback = SimpleNamespace(
            closed=False,
            get=AsyncMock(),
            post=AsyncMock(return_value=_FakeResponse(status=400, text='["bad"]')),
            delete=AsyncMock(),
            put=AsyncMock(),
        )
        client._client_session = session_fallback  # pylint: disable=protected-access
        fallback = await client._call_api("/v2/send", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(fallback["ok"])
        self.assertIn("failed", fallback["error"])

        session_blank_error = SimpleNamespace(
            closed=False,
            get=AsyncMock(),
            post=AsyncMock(return_value=_FakeResponse(status=400, text='{"error":"   "}')),
            delete=AsyncMock(),
            put=AsyncMock(),
        )
        client._client_session = session_blank_error  # pylint: disable=protected-access
        blank_error = await client._call_api("/v2/send", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(blank_error["ok"])
        self.assertIn("failed", blank_error["error"])

        session_exception = SimpleNamespace(
            closed=False,
            get=AsyncMock(),
            post=AsyncMock(side_effect=RuntimeError("down")),
            delete=AsyncMock(),
            put=AsyncMock(),
        )
        client._client_session = session_exception  # pylint: disable=protected-access
        client._max_api_retries = 0  # pylint: disable=protected-access
        exception_result = await client._call_api("/v2/send", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(exception_result["ok"])
        self.assertIn("request error", exception_result["error"])

        session_exception_retry = SimpleNamespace(
            closed=False,
            get=AsyncMock(),
            post=AsyncMock(side_effect=[RuntimeError("one"), RuntimeError("two")]),
            delete=AsyncMock(),
            put=AsyncMock(),
        )
        client._client_session = session_exception_retry  # pylint: disable=protected-access
        client._max_api_retries = 1  # pylint: disable=protected-access
        with patch("mugen.core.client.signal.asyncio.sleep", new=AsyncMock(return_value=None)):
            exception_retry = await client._call_api("/v2/send", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(exception_retry["ok"])
        self.assertIn("request error", exception_retry["error"])

    async def test_call_api_unsupported_method_and_init_when_missing_session(self) -> None:
        client = DefaultSignalClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        response = _FakeResponse(status=200, text='{"ok": true, "result": {}}')
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            post=AsyncMock(return_value=response),
            get=AsyncMock(return_value=response),
            delete=AsyncMock(return_value=response),
            put=AsyncMock(return_value=response),
        )

        unsupported_method = SimpleNamespace(value="BOGUS")
        unsupported = await client._call_api(  # pylint: disable=protected-access
            "/v2/send",
            method=unsupported_method,  # type: ignore[arg-type]
            payload={"x": 1},
        )
        self.assertFalse(unsupported["ok"])
        self.assertIn("Unsupported HTTP method", unsupported["error"])

        async def _init_client_session() -> None:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                post=AsyncMock(return_value=response),
                get=AsyncMock(return_value=response),
                delete=AsyncMock(return_value=response),
                put=AsyncMock(return_value=response),
            )

        with patch.object(
            client,
            "init",
            new=AsyncMock(side_effect=_init_client_session),
        ) as init_mock:
            client._client_session = None  # pylint: disable=protected-access
            await client._call_api("/v2/send", payload={"x": 1})  # pylint: disable=protected-access
            init_mock.assert_awaited_once()

        client._max_api_retries = -1  # pylint: disable=protected-access
        no_retry_loop = await client._call_api("/v2/send", payload={"x": 1})  # pylint: disable=protected-access
        self.assertFalse(no_retry_loop["ok"])
        self.assertIn("failed", no_retry_loop["error"])

    async def test_verify_startup_success_and_failure(self) -> None:
        client = DefaultSignalClient(
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
            new=AsyncMock(
                side_effect=[
                    {"ok": True, "status": 200},
                    {"ok": True, "status": 200, "data": {"mode": "json-rpc"}},
                ]
            ),
        ):
            self.assertTrue(await client.verify_startup())

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": False, "status": 500}),
        ):
            self.assertFalse(await client.verify_startup())

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(
                side_effect=[
                    {"ok": True, "status": 200},
                    {"ok": False, "status": 500},
                ]
            ),
        ):
            self.assertFalse(await client.verify_startup())

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(
                side_effect=[
                    {"ok": True, "status": 200},
                    {"ok": True, "status": 200, "data": ["bad"]},
                ]
            ),
        ):
            self.assertFalse(await client.verify_startup())

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(
                side_effect=[
                    {"ok": True, "status": 200},
                    {"ok": True, "status": 200, "data": {"mode": "webhook"}},
                ]
            ),
        ):
            self.assertFalse(await client.verify_startup())

    async def test_receive_events_paths(self) -> None:
        logger = Mock()
        client = DefaultSignalClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logger,
            messaging_service=Mock(),
            user_service=Mock(),
        )

        websocket = _FakeWebSocket(
            [
                _FakeWSMessage(msg_type=aiohttp.WSMsgType.TEXT, data='{"a":1}'),
                _FakeWSMessage(msg_type=aiohttp.WSMsgType.TEXT, data='["bad"]'),
                _FakeWSMessage(msg_type=aiohttp.WSMsgType.BINARY, data=b"x"),
            ]
        )
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            ws_connect=Mock(return_value=_FakeWSContext(websocket)),
        )

        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            events = []
            async for event in client.receive_events():
                events.append(event)

        self.assertEqual(events, [{"a": 1}])
        self.assertTrue(
            any(
                "Signal websocket payload is not an object." in str(call.args[0])
                for call in logger.warning.call_args_list
            )
        )
        self.assertTrue(
            any(
                "Signal websocket message ignored" in str(call.args[0])
                for call in logger.debug.call_args_list
            )
        )

        websocket_error = _FakeWebSocket(
            [_FakeWSMessage(msg_type=aiohttp.WSMsgType.ERROR)],
            error=RuntimeError("ws error"),
        )
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            ws_connect=Mock(return_value=_FakeWSContext(websocket_error)),
        )
        with self.assertRaisesRegex(RuntimeError, "websocket error"):
            async for _ in client.receive_events():
                pass

        websocket_closed = _FakeWebSocket([_FakeWSMessage(msg_type=aiohttp.WSMsgType.CLOSED)])
        client._client_session = SimpleNamespace(  # pylint: disable=protected-access
            closed=False,
            ws_connect=Mock(return_value=_FakeWSContext(websocket_closed)),
        )
        with self.assertRaisesRegex(RuntimeError, "websocket closed"):
            async for _ in client.receive_events():
                pass

        init_socket = _FakeWebSocket([_FakeWSMessage(msg_type=aiohttp.WSMsgType.CLOSED)])

        async def _init_missing_session() -> None:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                ws_connect=Mock(return_value=_FakeWSContext(init_socket)),
            )

        client._client_session = None  # pylint: disable=protected-access
        with patch.object(client, "init", new=AsyncMock(side_effect=_init_missing_session)) as init_mock:
            with self.assertRaisesRegex(RuntimeError, "websocket closed"):
                async for _ in client.receive_events():
                    pass
        init_mock.assert_awaited_once()

    async def test_send_operations_and_processing_signal_paths(self) -> None:
        client = DefaultSignalClient(
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
            self.assertFalse(
                (
                    await client.send_text_message(
                        recipient="  ",
                        text="hello",
                    )
                )["ok"]
            )
            self.assertFalse(
                (
                    await client.send_text_message(
                        recipient="+1555",
                        text="  ",
                    )
                )["ok"]
            )
            await client.send_text_message(recipient="+1555", text="hello")
            self.assertEqual(call_api.await_args_list[-1].args[0], "/v2/send")

            self.assertFalse(
                (
                    await client.send_media_message(
                        recipient="  ",
                        base64_attachments=["x"],
                    )
                )["ok"]
            )
            self.assertFalse(
                (
                    await client.send_media_message(
                        recipient="+1555",
                        base64_attachments=[],
                    )
                )["ok"]
            )
            await client.send_media_message(
                recipient="+1555",
                message="caption",
                base64_attachments=["base64://x"],
            )
            self.assertEqual(call_api.await_args_list[-1].args[0], "/v2/send")
            await client.send_media_message(
                recipient="+1555",
                base64_attachments=["base64://y"],
            )
            self.assertNotIn("message", call_api.await_args_list[-1].kwargs["payload"])

            self.assertFalse(
                (
                    await client.send_reaction(
                        recipient="",
                        reaction=":)",
                        target_author="+1",
                        timestamp=1,
                    )
                )["ok"]
            )
            self.assertFalse(
                (
                    await client.send_reaction(
                        recipient="+1",
                        reaction="",
                        target_author="+2",
                        timestamp=1,
                    )
                )["ok"]
            )
            await client.send_reaction(
                recipient="+1",
                reaction=":)",
                target_author="+2",
                timestamp=1,
                remove=False,
            )
            self.assertEqual(call_api.await_args_list[-1].kwargs["method"], HTTPMethod.POST)
            await client.send_reaction(
                recipient="+1",
                reaction=":)",
                target_author="+2",
                timestamp=1,
                remove=True,
            )
            self.assertEqual(call_api.await_args_list[-1].kwargs["method"], HTTPMethod.DELETE)

            self.assertFalse(
                (
                    await client.send_receipt(
                        recipient="",
                        receipt_type="read",
                        timestamp=1,
                    )
                )["ok"]
            )
            self.assertFalse(
                (
                    await client.send_receipt(
                        recipient="+1",
                        receipt_type="",
                        timestamp=1,
                    )
                )["ok"]
            )
            await client.send_receipt(
                recipient="+1",
                receipt_type="READ",
                timestamp=1,
            )
            self.assertEqual(call_api.await_args_list[-1].args[0], "/v1/receipts/%2B15550000001")

            self.assertTrue(await client.emit_processing_signal("+1", state="start"))
            self.assertEqual(call_api.await_args_list[-1].kwargs["method"], HTTPMethod.PUT)
            self.assertTrue(await client.emit_processing_signal("+1", state="stop"))
            self.assertEqual(call_api.await_args_list[-1].kwargs["method"], HTTPMethod.DELETE)
            self.assertFalse(await client.emit_processing_signal("", state="start"))
            self.assertFalse(await client.emit_processing_signal("+1", state="invalid"))
            with patch(
                "mugen.core.client.signal.normalize_processing_state",
                return_value="pause",
            ):
                self.assertFalse(await client.emit_processing_signal("+1", state="start"))

        config_typing_off = _make_config()
        config_typing_off.signal.typing.enabled = False
        typing_off_client = DefaultSignalClient(
            config=config_typing_off,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertIsNone(await typing_off_client.emit_processing_signal("+1", state="start"))

    async def test_download_attachment_paths(self) -> None:
        client = DefaultSignalClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        self.assertIsNone(await client.download_attachment("  "))

        response_ok = _FakeResponse(
            status=200,
            headers={"Content-Type": "image/png"},
            blob=b"\x89PNG",
        )
        response_404 = _FakeResponse(status=404, text="missing")
        response_disallowed = _FakeResponse(
            status=200,
            headers={"Content-Type": "model/gltf+json"},
            blob=b"%PDF",
        )
        response_large = _FakeResponse(
            status=200,
            headers={"Content-Type": "image/png"},
            blob=b"x" * 2048,
        )
        response_empty_type = _FakeResponse(
            status=200,
            headers={"Content-Type": ""},
            blob=b"abc",
        )
        session = SimpleNamespace(
            closed=False,
            get=AsyncMock(
                side_effect=[
                    response_404,
                    response_disallowed,
                    response_large,
                    response_empty_type,
                    response_ok,
                    RuntimeError("down"),
                ]
            ),
        )
        client._client_session = session  # pylint: disable=protected-access

        self.assertIsNone(await client.download_attachment("att-1"))
        self.assertIsNone(await client.download_attachment("att-2"))
        self.assertIsNone(await client.download_attachment("att-3"))
        fallback_type = await client.download_attachment("att-4")
        self.assertIsNotNone(fallback_type)
        self.assertEqual(fallback_type["mime_type"], "application/octet-stream")
        downloaded = await client.download_attachment("att-5")
        self.assertIsNotNone(downloaded)
        self.assertTrue(os.path.isfile(downloaded["path"]))
        self.assertEqual(downloaded["mime_type"], "image/png")
        self.assertIsNone(await client.download_attachment("att-6"))

        os.unlink(fallback_type["path"])
        os.unlink(downloaded["path"])

    async def test_download_attachment_inits_when_session_missing(self) -> None:
        client = DefaultSignalClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

        response_ok = _FakeResponse(
            status=200,
            headers={"Content-Type": "image/png"},
            blob=b"\x89PNG",
        )

        async def _init_client_session() -> None:
            client._client_session = SimpleNamespace(  # pylint: disable=protected-access
                closed=False,
                get=AsyncMock(return_value=response_ok),
            )

        client._client_session = None  # pylint: disable=protected-access
        with patch.object(client, "init", new=AsyncMock(side_effect=_init_client_session)) as init_mock:
            downloaded = await client.download_attachment("att-init")
        init_mock.assert_awaited_once()
        self.assertIsNotNone(downloaded)
        os.unlink(downloaded["path"])

    async def test_resolve_parsers_default_branches(self) -> None:
        config = _make_config()
        config.signal.api.timeout_seconds = None
        config.signal.api.max_api_retries = "bad"
        config.signal.api.retry_backoff_seconds = None
        config.signal.receive.heartbeat_seconds = None
        config.signal.media.max_download_bytes = "bad"
        config.signal.typing.enabled = "off"
        config.signal.media.allowed_mimetypes = [None, "", "image/*"]
        client = DefaultSignalClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(client._max_api_retries, 2)  # pylint: disable=protected-access
        self.assertEqual(client._retry_backoff_seconds, 0.5)  # pylint: disable=protected-access
        self.assertEqual(client._receive_heartbeat_seconds, 30.0)  # pylint: disable=protected-access
        self.assertEqual(client._max_download_bytes, 20 * 1024 * 1024)  # pylint: disable=protected-access
        self.assertFalse(client._typing_enabled)  # pylint: disable=protected-access
        self.assertEqual(client._allowed_mimetypes, ["image/*"])  # pylint: disable=protected-access

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            self.assertTrue(client._mime_type_allowed("image/png"))  # pylint: disable=protected-access
            self.assertFalse(client._mime_type_allowed("audio/mp3"))  # pylint: disable=protected-access
            _ = path
        finally:
            os.unlink(path)

        config_open_mime = _make_config()
        config_open_mime.signal.media.allowed_mimetypes = []
        client_open_mime = DefaultSignalClient(
            config=config_open_mime,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertTrue(client_open_mime._mime_type_allowed("model/gltf+json"))  # pylint: disable=protected-access

        config_negative_limits = _make_config()
        config_negative_limits.signal.api.max_api_retries = -1
        config_negative_limits.signal.media.max_download_bytes = 0
        client_negative_limits = DefaultSignalClient(
            config=config_negative_limits,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(client_negative_limits._max_api_retries, 2)  # pylint: disable=protected-access
        self.assertEqual(client_negative_limits._max_download_bytes, 20 * 1024 * 1024)  # pylint: disable=protected-access
