"""Unit tests for mugen.core.client.wechat.DefaultWeChatClient."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from http import HTTPMethod
from io import BytesIO
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.client.wechat import DefaultWeChatClient


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

    def release(self) -> None:
        return None

    def close(self) -> None:
        return None


def _make_config(*, provider: str = "official_account", typing_enabled: bool = True):
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
        wechat=SimpleNamespace(
            provider=provider,
            api=SimpleNamespace(
                timeout_seconds=10.0,
                max_api_retries=2,
                retry_backoff_seconds=0.1,
                max_download_bytes=1024,
            ),
            typing=SimpleNamespace(enabled=typing_enabled),
            official_account=SimpleNamespace(
                app_id="wx-app-id",
                app_secret="wx-app-secret",
            ),
            wecom=SimpleNamespace(
                corp_id="corp-id",
                corp_secret="corp-secret",
                agent_id=1000002,
            ),
        ),
    )


def _new_client(*, provider: str = "official_account", typing_enabled: bool = True):
    return DefaultWeChatClient(
        config=_make_config(provider=provider, typing_enabled=typing_enabled),
        ipc_service=Mock(),
        keyval_storage_gateway=Mock(),
        logging_gateway=Mock(),
        messaging_service=Mock(),
        user_service=Mock(),
    )


class TestMugenClientWeChat(unittest.IsolatedAsyncioTestCase):
    """Covers startup, retries, provider mapping, and media behavior."""

    async def test_init_and_close_happy_path(self) -> None:
        client = _new_client()
        session = Mock()
        session.closed = False
        session.close = AsyncMock()

        with patch(
            "mugen.core.client.wechat.aiohttp.ClientSession",
            return_value=session,
        ):
            await client.init()
            await client.close()

        session.close.assert_awaited_once()

    async def test_init_is_idempotent_and_close_error_paths(self) -> None:
        client = _new_client()
        existing_session = Mock()
        existing_session.closed = False
        existing_session.close = AsyncMock()
        client._client_session = existing_session  # pylint: disable=protected-access

        with patch("mugen.core.client.wechat.aiohttp.ClientSession") as session_cls:
            await client.init()
        session_cls.assert_not_called()

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
            "mugen.core.client.wechat.asyncio.wait_for",
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
            "mugen.core.client.wechat.asyncio.wait_for",
            new=AsyncMock(side_effect=_raise_runtime),
        ):
            with self.assertRaisesRegex(RuntimeError, "close failed"):
                await client.close()

    async def test_constructor_provider_and_path_helpers(self) -> None:
        client_oa = _new_client(provider="official_account")
        client_wecom = _new_client(provider="wecom")

        self.assertEqual(client_oa._provider_send_path(), "message/custom/send")  # pylint: disable=protected-access
        self.assertEqual(client_wecom._provider_send_path(), "message/send")  # pylint: disable=protected-access
        self.assertEqual(client_oa._provider_typing_path(), "message/custom/typing")  # pylint: disable=protected-access
        self.assertEqual(client_wecom._provider_typing_path(), "message/typing")  # pylint: disable=protected-access
        self.assertTrue(client_oa._is_retryable_status(503))  # pylint: disable=protected-access
        self.assertFalse(client_oa._is_retryable_status(200))  # pylint: disable=protected-access
        self.assertEqual(client_oa._extract_media_id({"id": "x"}), "x")  # pylint: disable=protected-access
        self.assertEqual(client_oa._extract_media_id({"media_id": "y"}), "y")  # pylint: disable=protected-access
        self.assertIsNone(client_oa._extract_media_id({}))  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "wechat.provider"):
            _new_client(provider="bad-provider")

    async def test_verify_startup_and_token_fetch_paths(self) -> None:
        client = _new_client()
        with patch.object(
            client,
            "_ensure_access_token",
            new=AsyncMock(return_value="token-1"),
        ):
            self.assertTrue(await client.verify_startup())

        with patch.object(
            client,
            "_ensure_access_token",
            new=AsyncMock(return_value=None),
        ):
            self.assertFalse(await client.verify_startup())

        client_oa = _new_client(provider="official_account")
        with patch.object(client_oa, "_request", new=AsyncMock(return_value={"ok": True})) as request:
            await client_oa._fetch_access_token()  # pylint: disable=protected-access
        self.assertIn("/token", request.await_args.kwargs["url"])

        client_wecom = _new_client(provider="wecom")
        with patch.object(client_wecom, "_request", new=AsyncMock(return_value={"ok": True})) as request:
            await client_wecom._fetch_access_token()  # pylint: disable=protected-access
        self.assertIn("/gettoken", request.await_args.kwargs["url"])

    async def test_ensure_access_token_uses_cache_and_parses_fetch_response(self) -> None:
        client = _new_client()
        client._access_token = "cached-token"  # pylint: disable=protected-access
        client._access_token_expires_at = client._now_utc() + timedelta(hours=1)  # pylint: disable=protected-access
        self.assertEqual(await client._ensure_access_token(), "cached-token")  # pylint: disable=protected-access

        client._access_token = None  # pylint: disable=protected-access
        client._access_token_expires_at = None  # pylint: disable=protected-access
        with patch.object(
            client,
            "_fetch_access_token",
            new=AsyncMock(
                return_value={"data": {"access_token": "fresh-token", "expires_in": 120}}
            ),
        ):
            token = await client._ensure_access_token()  # pylint: disable=protected-access
        self.assertEqual(token, "fresh-token")

        with patch.object(
            client,
            "_fetch_access_token",
            new=AsyncMock(return_value={"data": {"expires_in": 120}}),
        ):
            client._access_token = None  # pylint: disable=protected-access
            client._access_token_expires_at = None  # pylint: disable=protected-access
            self.assertIsNone(await client._ensure_access_token())  # pylint: disable=protected-access

    async def test_request_success_retry_provider_error_and_exception_paths(self) -> None:
        client = _new_client()
        client._max_api_retries = 1  # pylint: disable=protected-access
        client._retry_backoff_seconds = 0.0  # pylint: disable=protected-access

        @asynccontextmanager
        async def _ctx_success(**_kwargs):
            yield _FakeResponse(status=200, text='{"errcode":0,"ok":true}')

        with (
            patch.object(client, "_ensure_access_token", new=AsyncMock(return_value="token-1")),
            patch.object(client, "_request_context", new=_ctx_success),
        ):
            response = await client._request(  # pylint: disable=protected-access
                method=HTTPMethod.POST,
                url="https://example.test/send",
            )
        self.assertTrue(response["ok"])

        responses = [
            _FakeResponse(status=503, text='{"errcode":0,"ok":false}'),
            _FakeResponse(status=200, text='{"errcode":0,"ok":true}'),
        ]

        @asynccontextmanager
        async def _ctx_retry(**_kwargs):
            yield responses.pop(0)

        with (
            patch.object(client, "_ensure_access_token", new=AsyncMock(return_value="token-1")),
            patch.object(client, "_request_context", new=_ctx_retry),
            patch("mugen.core.client.wechat.asyncio.sleep", new=AsyncMock(return_value=None)),
        ):
            response = await client._request(  # pylint: disable=protected-access
                method=HTTPMethod.POST,
                url="https://example.test/send",
            )
        self.assertTrue(response["ok"])

        @asynccontextmanager
        async def _ctx_provider_error(**_kwargs):
            yield _FakeResponse(status=200, text='{"errcode":40001,"errmsg":"bad"}')

        with (
            patch.object(client, "_ensure_access_token", new=AsyncMock(return_value="token-1")),
            patch.object(client, "_request_context", new=_ctx_provider_error),
        ):
            response = await client._request(  # pylint: disable=protected-access
                method=HTTPMethod.POST,
                url="https://example.test/send",
            )
        self.assertFalse(response["ok"])
        self.assertIn("errcode=40001", response["error"])

        with patch.object(client, "_ensure_access_token", new=AsyncMock(return_value=None)):
            response = await client._request(  # pylint: disable=protected-access
                method=HTTPMethod.POST,
                url="https://example.test/send",
            )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "access token unavailable")

        with (
            patch.object(client, "_ensure_access_token", new=AsyncMock(return_value="token-1")),
            patch.object(client, "_request_context", side_effect=RuntimeError("down")),
            patch("mugen.core.client.wechat.asyncio.sleep", new=AsyncMock(return_value=None)),
        ):
            response = await client._request(  # pylint: disable=protected-access
                method=HTTPMethod.POST,
                url="https://example.test/send",
            )
        self.assertFalse(response["ok"])
        self.assertIn("request error", response["error"])

    async def test_build_payload_and_send_message_methods(self) -> None:
        client_oa = _new_client(provider="official_account")
        client_wecom = _new_client(provider="wecom")

        payload_oa = client_oa._build_message_payload(  # pylint: disable=protected-access
            recipient="u1",
            msg_type="text",
            content={"content": "hello"},
        )
        self.assertEqual(payload_oa["touser"], "u1")
        self.assertNotIn("agentid", payload_oa)

        payload_wecom = client_wecom._build_message_payload(  # pylint: disable=protected-access
            recipient="u2",
            msg_type="text",
            content={"content": "hello"},
        )
        self.assertEqual(payload_wecom["agentid"], 1000002)

        with patch.object(client_oa, "_call_api", new=AsyncMock(return_value={"ok": True})) as call_api:
            await client_oa.send_text_message(recipient="u1", text="hello")
            await client_oa.send_raw_message(payload={"raw": 1})
        self.assertEqual(call_api.await_count, 2)

        with patch.object(client_oa, "_call_api", new=AsyncMock(return_value={"ok": True})) as call_api:
            await client_oa.send_audio_message(recipient="u1", audio={"media_id": "a1"})
            await client_oa.send_file_message(recipient="u1", file={"media_id": "f1"})
            await client_oa.send_image_message(recipient="u1", image={"media_id": "i1"})
            await client_oa.send_video_message(recipient="u1", video={"media_id": "v1"})
        self.assertEqual(call_api.await_count, 4)

        self.assertIsNone(await client_oa.send_audio_message(recipient="u1", audio={}))
        self.assertIsNone(await client_oa.send_file_message(recipient="u1", file={}))
        self.assertIsNone(await client_oa.send_image_message(recipient="u1", image={}))
        self.assertIsNone(await client_oa.send_video_message(recipient="u1", video={}))

    async def test_upload_media_and_download_media_and_typing_signal(self) -> None:
        client = _new_client()

        self.assertIsNone(await client.upload_media(file_path=BytesIO(b"1"), media_type=""))
        self.assertIsNone(await client.upload_media(file_path="/tmp/missing.file", media_type="image"))
        self.assertIsNone(await client.upload_media(file_path=123, media_type="image"))  # type: ignore[arg-type]

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"hello")
            file_path = handle.name
        self.addCleanup(lambda: os.path.exists(file_path) and os.unlink(file_path))

        with patch.object(client, "_call_api", new=AsyncMock(return_value={"ok": True})) as call_api:
            await client.upload_media(file_path=file_path, media_type="image")
            await client.upload_media(file_path=BytesIO(b"hello"), media_type="image")
        self.assertEqual(call_api.await_count, 2)

        self.assertIsNone(await client.download_media(media_id=""))
        with patch.object(
            client,
            "_download_binary",
            new=AsyncMock(return_value={"path": "/tmp/file.bin"}),
        ):
            downloaded = await client.download_media(media_id="m-1")
        self.assertEqual(downloaded["path"], "/tmp/file.bin")

        client_typing_off = _new_client(typing_enabled=False)
        self.assertIsNone(
            await client_typing_off.emit_processing_signal("u1", state="start")
        )

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value={"ok": True}),
        ) as call_api:
            self.assertTrue(await client.emit_processing_signal("u1", state="start"))
            self.assertTrue(await client.emit_processing_signal("u1", state="stop"))
        self.assertEqual(call_api.await_count, 2)

        with patch.object(
            client,
            "_call_api",
            new=AsyncMock(return_value=None),
        ):
            self.assertFalse(await client.emit_processing_signal("u1", state="start"))

    async def test_download_binary_paths(self) -> None:
        client = _new_client()

        with patch.object(client, "_ensure_access_token", new=AsyncMock(return_value=None)):
            self.assertIsNone(
                await client._download_binary(  # pylint: disable=protected-access
                    path="media/get",
                    params={"media_id": "m-1"},
                )
            )

        @asynccontextmanager
        async def _ctx_http_error(**_kwargs):
            yield _FakeResponse(status=500, blob=b"down")

        with (
            patch.object(client, "_ensure_access_token", new=AsyncMock(return_value="token-1")),
            patch.object(client, "_request_context", new=_ctx_http_error),
        ):
            self.assertIsNone(
                await client._download_binary(  # pylint: disable=protected-access
                    path="media/get",
                    params={"media_id": "m-1"},
                )
            )

        @asynccontextmanager
        async def _ctx_json(**_kwargs):
            yield _FakeResponse(
                status=200,
                blob=b'{"errcode":40007}',
                headers={"Content-Type": "application/json"},
            )

        with (
            patch.object(client, "_ensure_access_token", new=AsyncMock(return_value="token-1")),
            patch.object(client, "_request_context", new=_ctx_json),
        ):
            self.assertIsNone(
                await client._download_binary(  # pylint: disable=protected-access
                    path="media/get",
                    params={"media_id": "m-1"},
                )
            )

        @asynccontextmanager
        async def _ctx_too_large(**_kwargs):
            yield _FakeResponse(
                status=200,
                blob=b"x" * 2048,
                headers={"Content-Type": "application/octet-stream"},
            )

        with (
            patch.object(client, "_ensure_access_token", new=AsyncMock(return_value="token-1")),
            patch.object(client, "_request_context", new=_ctx_too_large),
        ):
            self.assertIsNone(
                await client._download_binary(  # pylint: disable=protected-access
                    path="media/get",
                    params={"media_id": "m-1"},
                )
            )

        @asynccontextmanager
        async def _ctx_success(**_kwargs):
            yield _FakeResponse(
                status=200,
                blob=b"hello",
                headers={"Content-Type": "audio/ogg"},
            )

        with (
            patch.object(client, "_ensure_access_token", new=AsyncMock(return_value="token-1")),
            patch.object(client, "_request_context", new=_ctx_success),
        ):
            payload = await client._download_binary(  # pylint: disable=protected-access
                path="media/get",
                params={"media_id": "m-1"},
            )
        self.assertIsNotNone(payload)
        self.assertTrue(os.path.isfile(payload["path"]))
        os.unlink(payload["path"])

    async def test_constructor_defaults_and_static_helpers(self) -> None:
        cfg_invalid = _make_config()
        cfg_invalid.wechat.api.timeout_seconds = None
        cfg_invalid.wechat.api.max_download_bytes = "invalid"
        cfg_invalid.wechat.api.max_api_retries = "invalid"
        client_invalid = DefaultWeChatClient(
            config=cfg_invalid,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(client_invalid._http_timeout_seconds, 10.0)  # pylint: disable=protected-access
        self.assertEqual(client_invalid._max_download_bytes, 20 * 1024 * 1024)  # pylint: disable=protected-access
        self.assertEqual(client_invalid._max_api_retries, 2)  # pylint: disable=protected-access

        cfg_nonpositive = _make_config()
        cfg_nonpositive.wechat.api.max_download_bytes = 0
        cfg_nonpositive.wechat.api.max_api_retries = -1
        client_nonpositive = DefaultWeChatClient(
            config=cfg_nonpositive,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(client_nonpositive._max_download_bytes, 20 * 1024 * 1024)  # pylint: disable=protected-access
        self.assertEqual(client_nonpositive._max_api_retries, 2)  # pylint: disable=protected-access

        self.assertEqual(client_nonpositive._resolve_correlation_id("cid-1"), "cid-1")  # pylint: disable=protected-access
        self.assertIsNone(client_nonpositive._parse_response_payload(""))  # pylint: disable=protected-access
        self.assertIsNone(client_nonpositive._parse_response_payload("{"))  # pylint: disable=protected-access
        self.assertIsNone(client_nonpositive._parse_response_payload("[]"))  # pylint: disable=protected-access
        self.assertIsNone(client_nonpositive._provider_error(None))  # pylint: disable=protected-access

    async def test_close_handles_missing_and_preclosed_sessions(self) -> None:
        client = _new_client()
        await client.close()

        closed_session = Mock()
        closed_session.closed = True
        client._client_session = closed_session  # pylint: disable=protected-access
        await client.close()
        self.assertIsNone(client._client_session)  # pylint: disable=protected-access

    async def test_ensure_access_token_non_dict_payload_and_expiry_coercion(self) -> None:
        client = _new_client()

        with patch.object(
            client,
            "_fetch_access_token",
            new=AsyncMock(return_value={"ok": False}),
        ):
            self.assertIsNone(await client._ensure_access_token())  # pylint: disable=protected-access

        with patch.object(
            client,
            "_fetch_access_token",
            new=AsyncMock(
                return_value={
                    "data": {
                        "access_token": "token-bad-expiry",
                        "expires_in": "bad",
                    }
                }
            ),
        ):
            token = await client._ensure_access_token()  # pylint: disable=protected-access
        self.assertEqual(token, "token-bad-expiry")
        self.assertGreater(client._access_token_expires_at, client._now_utc())  # pylint: disable=protected-access

        client._access_token = None  # pylint: disable=protected-access
        client._access_token_expires_at = None  # pylint: disable=protected-access
        with patch.object(
            client,
            "_fetch_access_token",
            new=AsyncMock(
                return_value={
                    "data": {
                        "access_token": "token-zero-expiry",
                        "expires_in": 0,
                    }
                }
            ),
        ):
            token = await client._ensure_access_token()  # pylint: disable=protected-access
        self.assertEqual(token, "token-zero-expiry")
        self.assertGreater(client._access_token_expires_at, client._now_utc())  # pylint: disable=protected-access

    async def test_request_context_and_request_without_token_branches(self) -> None:
        client = _new_client()

        with self.assertRaisesRegex(RuntimeError, "session unavailable"):
            async with client._request_context(  # pylint: disable=protected-access
                method=HTTPMethod.GET,
                url="https://example.test",
                params=None,
                payload=None,
            ):
                pass

        get_response = Mock()
        get_response.release = Mock()
        get_response.close = Mock()
        post_response = Mock()
        post_response.release = Mock()
        post_response.close = Mock()

        session = Mock()
        session.closed = False
        session.get = AsyncMock(return_value=get_response)
        session.post = AsyncMock(return_value=post_response)
        client._client_session = session  # pylint: disable=protected-access

        async with client._request_context(  # pylint: disable=protected-access
            method=HTTPMethod.GET,
            url="https://example.test/get",
            params={"k": "v"},
            payload=None,
            headers={"x": "1"},
        ) as response:
            self.assertIs(response, get_response)
        session.get.assert_awaited_once()
        get_response.release.assert_called_once()
        get_response.close.assert_called_once()

        async with client._request_context(  # pylint: disable=protected-access
            method=HTTPMethod.POST,
            url="https://example.test/post",
            params=None,
            payload={"x": 1},
            data=b"abc",
            headers={"x": "2"},
        ) as response:
            self.assertIs(response, post_response)
        session.post.assert_awaited_once()
        post_response.release.assert_called_once()
        post_response.close.assert_called_once()

        # Exercise branch where optional headers are omitted.
        get_response_no_headers = Mock()
        get_response_no_headers.release = Mock()
        get_response_no_headers.close = Mock()
        session.get = AsyncMock(return_value=get_response_no_headers)
        async with client._request_context(  # pylint: disable=protected-access
            method=HTTPMethod.GET,
            url="https://example.test/get-no-headers",
            params=None,
            payload=None,
            headers=None,
        ):
            ...
        get_response_no_headers.release.assert_called_once()
        get_response_no_headers.close.assert_called_once()

        client._max_api_retries = -1  # pylint: disable=protected-access
        response = await client._request(  # pylint: disable=protected-access
            method=HTTPMethod.GET,
            url="https://example.test/no-loop",
            include_token=False,
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "request not attempted")

        @asynccontextmanager
        async def _ctx_ok(**_kwargs):
            yield _FakeResponse(status=200, text='{"errcode":0}')

        client._max_api_retries = 0  # pylint: disable=protected-access
        with (
            patch.object(
                client,
                "_ensure_access_token",
                new=AsyncMock(side_effect=AssertionError("must not be called")),
            ),
            patch.object(client, "_request_context", new=_ctx_ok),
        ):
            response = await client._request(  # pylint: disable=protected-access
                method=HTTPMethod.POST,
                url="https://example.test/include-false",
                include_token=False,
            )
        self.assertTrue(response["ok"])

        with patch.object(client, "_request", new=AsyncMock(return_value={"ok": True})) as request:
            await client._call_api(  # pylint: disable=protected-access
                path="/message/send",
                method=HTTPMethod.GET,
                include_token=False,
                params={"x": 1},
            )
        self.assertEqual(
            request.await_args.kwargs["url"],
            "https://api.weixin.qq.com/cgi-bin/message/send",
        )

    async def test_download_binary_exception_path(self) -> None:
        client = _new_client()

        with (
            patch.object(
                client,
                "_ensure_access_token",
                new=AsyncMock(return_value="token-1"),
            ),
            patch.object(
                client,
                "_request_context",
                side_effect=RuntimeError("network down"),
            ),
        ):
            result = await client._download_binary(  # pylint: disable=protected-access
                path="media/get",
                params={"media_id": "m-1"},
            )
        self.assertIsNone(result)
        client._logging_gateway.error.assert_called()  # pylint: disable=protected-access
