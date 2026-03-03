"""Unit tests for mugen.core.client.whatsapp.DefaultWhatsAppClient."""

import asyncio
from http import HTTPMethod
from io import BytesIO
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from mugen.core.client.whatsapp import DefaultWhatsAppClient


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        whatsapp=SimpleNamespace(
            graphapi=SimpleNamespace(
                base_url="https://graph.example.com",
                version="v19.0",
                access_token="TOKEN_123",
                typing_indicator_enabled=True,
            ),
            business=SimpleNamespace(phone_number_id="123456789"),
        )
    )


class _Response:
    def __init__(
        self,
        *,
        text: str = "",
        status: int = 200,
        body: bytes = b"",
        headers: dict | None = None,
    ):
        self._text = text
        self.status = status
        self._body = body
        self.headers = {} if headers is None else dict(headers)
        self.release_called = False
        self.close_called = False

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._body

    def release(self) -> None:
        self.release_called = True

    def close(self) -> None:
        self.close_called = True


class _ChunkStream:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _StreamResponse(_Response):
    def __init__(self, *, chunks: list[bytes], status: int = 200):
        super().__init__(status=status, body=b"")
        self.content = _ChunkStream(chunks)


class TestMugenClientWhatsApp(unittest.IsolatedAsyncioTestCase):
    """Covers API wrapper paths, media upload/download, and payload builders."""

    def _new_client(self) -> DefaultWhatsAppClient:
        return DefaultWhatsAppClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )

    async def test_init_and_close_manage_client_session(self) -> None:
        client = self._new_client()
        fake_session = Mock()
        fake_session.close = AsyncMock(return_value=None)
        fake_session.closed = False

        with patch(
            "mugen.core.client.whatsapp.aiohttp.ClientSession",
            return_value=fake_session,
        ):
            await client.init()

        await client.close()
        client._logging_gateway.debug.assert_any_call("DefaultWhatsAppClient.init")
        client._logging_gateway.debug.assert_any_call("DefaultWhatsAppClient.close")
        fake_session.close.assert_awaited_once()

    async def test_close_is_safe_without_init(self) -> None:
        client = self._new_client()

        await client.close()

        client._logging_gateway.debug.assert_called_with("DefaultWhatsAppClient.close")

    async def test_init_is_idempotent_when_session_exists(self) -> None:
        client = self._new_client()
        existing_session = Mock()
        existing_session.closed = False
        existing_session.close = AsyncMock(return_value=None)
        client._client_session = existing_session  # pylint: disable=protected-access

        with patch("mugen.core.client.whatsapp.aiohttp.ClientSession") as session_cls:
            await client.init()

        session_cls.assert_not_called()

    async def test_verify_startup_returns_true_on_2xx_probe(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(  # pylint: disable=protected-access
            return_value={"ok": True, "status": 200}
        )

        verified = await client.verify_startup()

        self.assertTrue(verified)
        kwargs = client._call_api.await_args.kwargs  # pylint: disable=protected-access
        self.assertEqual(kwargs["path"], "123456789")
        self.assertEqual(kwargs["method"], HTTPMethod.GET)
        self.assertIsInstance(kwargs["correlation_id"], str)
        self.assertNotEqual(kwargs["correlation_id"], "")

    async def test_verify_startup_logs_and_returns_false_on_probe_failure(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(  # pylint: disable=protected-access
            return_value={"ok": False, "status": 401, "error": "unauthorized"}
        )

        verified = await client.verify_startup()

        self.assertFalse(verified)
        client._logging_gateway.error.assert_called()
        self.assertIn(
            "WhatsApp startup probe failed",
            str(client._logging_gateway.error.call_args.args[0]),
        )

    async def test_close_skips_already_closed_session_and_clears_reference(
        self,
    ) -> None:
        client = self._new_client()
        existing_session = Mock()
        existing_session.closed = True
        existing_session.close = AsyncMock(return_value=None)
        client._client_session = existing_session  # pylint: disable=protected-access

        await client.close()

        existing_session.close.assert_not_awaited()
        self.assertIsNone(client._client_session)  # pylint: disable=protected-access

    async def test_close_logs_warning_when_session_close_times_out(self) -> None:
        client = self._new_client()
        existing_session = Mock()
        existing_session.closed = False
        existing_session.close = AsyncMock(return_value=None)
        client._client_session = existing_session  # pylint: disable=protected-access

        def _raise_timeout(awaitable, timeout):  # noqa: ARG001
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError

        with patch(
            "mugen.core.client.whatsapp.asyncio.wait_for",
            side_effect=_raise_timeout,
        ):
            await client.close()

        self.assertTrue(
            any(
                "WhatsApp client session close timed out" in str(call.args[0])
                for call in client._logging_gateway.warning.call_args_list
            )
        )

    async def test_resolve_shutdown_timeout_seconds_rejects_invalid_values(self) -> None:
        config = _make_config()
        config.mugen = SimpleNamespace(runtime=SimpleNamespace(shutdown_timeout_seconds="bad"))
        with self.assertRaisesRegex(RuntimeError, "shutdown_timeout_seconds"):
            DefaultWhatsAppClient(
                config=config,
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
                messaging_service=Mock(),
                user_service=Mock(),
            )

        config.mugen.runtime.shutdown_timeout_seconds = 12.5
        client = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(
            client._shutdown_timeout_seconds,  # pylint: disable=protected-access
            12.5,
        )
        config.mugen.runtime.shutdown_timeout_seconds = 0
        with self.assertRaisesRegex(RuntimeError, "shutdown_timeout_seconds"):
            DefaultWhatsAppClient(
                config=config,
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
                messaging_service=Mock(),
                user_service=Mock(),
            )

    async def test_resolve_config_values_reject_invalid_timeout_fields(self) -> None:
        config = _make_config()
        config.whatsapp.graphapi.timeout_seconds = "invalid"
        with self.assertRaisesRegex(RuntimeError, "timeout_seconds"):
            DefaultWhatsAppClient(
                config=config,
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
                messaging_service=Mock(),
                user_service=Mock(),
            )

        config = _make_config()
        config.whatsapp.graphapi.timeout_seconds = 10
        config.whatsapp.graphapi.retry_backoff_seconds = "bad"
        with self.assertRaisesRegex(RuntimeError, "retry_backoff_seconds"):
            DefaultWhatsAppClient(
                config=config,
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
                messaging_service=Mock(),
                user_service=Mock(),
            )

        config = _make_config()
        config.whatsapp.graphapi.timeout_seconds = 10
        config.whatsapp.graphapi.retry_backoff_seconds = 0.5
        config.whatsapp.graphapi.max_download_bytes = "bad"
        config.whatsapp.graphapi.max_api_retries = "bad"
        client = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(
            client._http_timeout_seconds, 10.0
        )  # pylint: disable=protected-access
        self.assertEqual(
            client._max_download_bytes, 20 * 1024 * 1024
        )  # pylint: disable=protected-access
        self.assertEqual(client._max_api_retries, 2)  # pylint: disable=protected-access
        self.assertEqual(
            client._retry_backoff_seconds, 0.5
        )  # pylint: disable=protected-access

    async def test_resolve_typing_indicator_enabled_string_variants(self) -> None:
        config = _make_config()
        config.whatsapp.graphapi.typing_indicator_enabled = "yes"
        client_true = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertTrue(client_true._typing_indicator_enabled)  # pylint: disable=protected-access

        config.whatsapp.graphapi.typing_indicator_enabled = "off"
        client_false = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertFalse(client_false._typing_indicator_enabled)  # pylint: disable=protected-access

        config.whatsapp.graphapi.typing_indicator_enabled = "unexpected"
        client_default = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertTrue(client_default._typing_indicator_enabled)  # pylint: disable=protected-access

        config.whatsapp.graphapi.typing_indicator_enabled = 123
        client_non_string = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertTrue(client_non_string._typing_indicator_enabled)  # pylint: disable=protected-access

        config.whatsapp.graphapi.timeout_seconds = 10
        config.whatsapp.graphapi.max_download_bytes = 0
        config.whatsapp.graphapi.max_api_retries = -1
        config.whatsapp.graphapi.retry_backoff_seconds = 0.5
        client = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(
            client._http_timeout_seconds, 10.0
        )  # pylint: disable=protected-access
        self.assertEqual(
            client._max_download_bytes, 20 * 1024 * 1024
        )  # pylint: disable=protected-access
        self.assertEqual(client._max_api_retries, 2)  # pylint: disable=protected-access
        self.assertEqual(
            client._retry_backoff_seconds, 0.5
        )  # pylint: disable=protected-access

        config.whatsapp.graphapi.timeout_seconds = -1
        with self.assertRaisesRegex(RuntimeError, "timeout_seconds"):
            DefaultWhatsAppClient(
                config=config,
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
                messaging_service=Mock(),
                user_service=Mock(),
            )
        config.whatsapp.graphapi.timeout_seconds = 10
        config.whatsapp.graphapi.retry_backoff_seconds = 0
        client_zero_backoff = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(
            client_zero_backoff._retry_backoff_seconds,  # pylint: disable=protected-access
            0.0,
        )

    async def test_api_wrapper_methods_delegate_to_internal_helpers(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(
            return_value={
                "ok": True,
                "status": 200,
                "data": {},
                "error": None,
                "raw": "{}",
            }
        )  # pylint: disable=protected-access
        client._download_file_http = AsyncMock(  # pylint: disable=protected-access
            return_value="/tmp/file.png"
        )

        self.assertEqual(
            await client.delete_media("media-id"),
            {"ok": True, "status": 200, "data": {}, "error": None, "raw": "{}"},
        )
        self.assertEqual(
            await client.retrieve_media_url("media-id"),
            {"ok": True, "status": 200, "data": {}, "error": None, "raw": "{}"},
        )
        self.assertEqual(
            await client.download_media("https://example.com/x", "image/png"),
            "/tmp/file.png",
        )
        client._call_api.assert_any_await(
            "media-id",
            method=HTTPMethod.DELETE,
            correlation_id="media-id",
        )
        client._call_api.assert_any_await(
            "media-id",
            method=HTTPMethod.GET,
            correlation_id="media-id",
        )
        client._download_file_http.assert_awaited_once_with(
            "https://example.com/x",
            "image/png",
            correlation_id="https://example.com/x",
        )

    def test_resolve_correlation_id_prefers_explicit_value(self) -> None:
        client = self._new_client()

        with patch.object(
            client,
            "_new_correlation_id",
            return_value="generated-cid",
        ) as new_cid:
            self.assertEqual(
                client._resolve_correlation_id("explicit-cid"),  # pylint: disable=protected-access
                "explicit-cid",
            )
            self.assertEqual(
                client._resolve_correlation_id(None),  # pylint: disable=protected-access
                "generated-cid",
            )
            new_cid.assert_called_once()

    async def test_send_message_payload_builders(self) -> None:
        client = self._new_client()
        client._send_message = AsyncMock(
            return_value={
                "ok": True,
                "status": 200,
                "data": {"messages": [{"id": "wamid-1"}]},
                "error": None,
                "raw": '{"messages":[{"id":"wamid-1"}]}',
            }
        )  # pylint: disable=protected-access

        cases = [
            ("send_audio_message", {"id": "a1"}, "audio", "audio"),
            (
                "send_contacts_message",
                [{"name": {"formatted_name": "A"}}],
                "contacts",
                "contacts",
            ),
            ("send_document_message", {"id": "d1"}, "document", "document"),
            ("send_image_message", {"id": "i1"}, "image", "image"),
            (
                "send_interactive_message",
                {"type": "button"},
                "interactive",
                "interactive",
            ),
            (
                "send_location_message",
                {"latitude": 1, "longitude": 2},
                "location",
                "location",
            ),
            ("send_sticker_message", {"id": "s1"}, "sticker", "sticker"),
            ("send_template_message", {"name": "tpl"}, "template", "template"),
            ("send_video_message", {"id": "v1"}, "video", "video"),
        ]

        for method_name, payload, msg_type, payload_key in cases:
            method = getattr(client, method_name)

            result = await method(payload, "15550001", reply_to="msg-1")
            self.assertTrue(result["ok"])
            data = client._send_message.await_args.kwargs["data"]
            self.assertEqual(data["type"], msg_type)
            self.assertEqual(data["to"], "+15550001")
            self.assertEqual(data[payload_key], payload)
            self.assertEqual(data["context"], {"message_id": "msg-1"})

            result_no_reply = await method(payload, "15550001")
            self.assertTrue(result_no_reply["ok"])
            data_no_reply = client._send_message.await_args.kwargs["data"]
            self.assertEqual(data_no_reply["type"], msg_type)
            self.assertNotIn("context", data_no_reply)

        text_result = await client.send_text_message(
            "hello", "15550002", reply_to="msg-2"
        )
        self.assertTrue(text_result["ok"])
        text_data = client._send_message.await_args.kwargs["data"]
        self.assertEqual(text_data["type"], "text")
        self.assertEqual(text_data["text"]["body"], "hello")
        self.assertTrue(text_data["text"]["preview_url"])
        self.assertEqual(text_data["context"], {"message_id": "msg-2"})

        await client.send_text_message("no reply", "15550002")
        text_data_no_reply = client._send_message.await_args.kwargs["data"]
        self.assertNotIn("context", text_data_no_reply)

        reaction_result = await client.send_reaction_message(
            {"emoji": "👍"}, "15550003"
        )
        self.assertTrue(reaction_result["ok"])
        reaction_data = client._send_message.await_args.kwargs["data"]
        self.assertEqual(reaction_data["type"], "reaction")
        self.assertEqual(reaction_data["reaction"], {"emoji": "👍"})

    async def test_send_text_message_normalizes_recipient_prefix(self) -> None:
        client = self._new_client()
        client._send_message = AsyncMock(
            return_value="sent"
        )  # pylint: disable=protected-access

        await client.send_text_message("hello", "+15550002")

        text_data = client._send_message.await_args.kwargs["data"]
        self.assertEqual(text_data["to"], "+15550002")

    async def test_emit_processing_signal_start_calls_graph_api(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(  # pylint: disable=protected-access
            return_value={"ok": True, "status": 200}
        )

        emitted = await client.emit_processing_signal(
            "15550009",
            state="start",
            message_id="wamid-1",
        )

        self.assertTrue(emitted)
        kwargs = client._call_api.await_args.kwargs  # pylint: disable=protected-access
        self.assertEqual(kwargs["path"], "123456789/messages")
        self.assertEqual(kwargs["correlation_id"], "wamid-1")
        self.assertEqual(kwargs["data"]["to"], "+15550009")
        self.assertEqual(kwargs["data"]["status"], "read")
        self.assertEqual(kwargs["data"]["message_id"], "wamid-1")
        self.assertEqual(kwargs["data"]["typing_indicator"], {"type": "text"})

    async def test_emit_processing_signal_stop_is_noop(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock()  # pylint: disable=protected-access

        emitted = await client.emit_processing_signal(
            "15550009",
            state="stop",
            message_id="wamid-1",
        )

        self.assertTrue(emitted)
        client._call_api.assert_not_awaited()  # pylint: disable=protected-access

    async def test_emit_processing_signal_disabled_short_circuits(self) -> None:
        config = _make_config()
        config.whatsapp.graphapi.typing_indicator_enabled = False
        client = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        client._call_api = AsyncMock()  # pylint: disable=protected-access

        emitted = await client.emit_processing_signal(
            "15550009",
            state="start",
            message_id="wamid-1",
        )

        self.assertIsNone(emitted)
        client._call_api.assert_not_awaited()  # pylint: disable=protected-access

    async def test_emit_processing_signal_failure_returns_false(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(  # pylint: disable=protected-access
            return_value={"ok": False, "status": 500}
        )

        invalid_state = await client.emit_processing_signal(
            "15550009",
            state="invalid",
            message_id="wamid-bad-state",
        )
        self.assertFalse(invalid_state)

        missing_recipient = await client.emit_processing_signal(
            "",
            state="start",
            message_id="wamid-bad-recipient",
        )
        self.assertFalse(missing_recipient)

        missing_message_id = await client.emit_processing_signal(
            "15550009",
            state="start",
            message_id=None,
        )
        self.assertFalse(missing_message_id)

        emitted = await client.emit_processing_signal(
            "15550009",
            state="start",
            message_id="wamid-2",
        )

        self.assertFalse(emitted)

        client._call_api = AsyncMock(side_effect=RuntimeError("api boom"))  # pylint: disable=protected-access
        api_exception = await client.emit_processing_signal(
            "15550009",
            state="start",
            message_id="wamid-3",
        )
        self.assertFalse(api_exception)

    async def test_upload_media_bytesio_and_file_path(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(
            return_value={
                "ok": True,
                "status": 200,
                "data": {"id": "media-id"},
                "error": None,
                "raw": '{"id":"media-id"}',
            }
        )  # pylint: disable=protected-access

        uploaded_from_bytes = await client.upload_media(BytesIO(b"abc"), "image/png")
        self.assertEqual(uploaded_from_bytes["data"]["id"], "media-id")
        first_call = client._call_api.await_args
        self.assertEqual(first_call.args[0], "123456789/media")
        self.assertIsNone(first_call.kwargs.get("files"))
        self.assertTrue(callable(first_call.kwargs["files_factory"]))
        first_form, first_resources = first_call.kwargs["files_factory"]()
        self.assertIsInstance(first_form, aiohttp.FormData)
        self.assertEqual(first_resources, [])

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"hello")
            path = tf.name
        try:
            uploaded_from_file = await client.upload_media(path, "text/plain")
            self.assertEqual(uploaded_from_file["data"]["id"], "media-id")
            second_call = client._call_api.await_args
            self.assertEqual(second_call.args[0], "123456789/media")
            self.assertIsNone(second_call.kwargs.get("files"))
            self.assertTrue(callable(second_call.kwargs["files_factory"]))
            second_form, second_resources = second_call.kwargs["files_factory"]()
            self.assertIsInstance(second_form, aiohttp.FormData)
            self.assertEqual(len(second_resources), 1)
            second_resources[0].close()
        finally:
            os.remove(path)

    async def test_upload_media_logs_and_returns_none_when_file_open_fails(
        self,
    ) -> None:
        client = self._new_client()

        result = await client.upload_media(
            "/tmp/does-not-exist.bin", "application/octet-stream"
        )

        self.assertFalse(result["ok"])
        client._logging_gateway.error.assert_called_once()

    async def test_call_api_all_methods_and_payload_options(self) -> None:
        client = self._new_client()
        session = Mock()
        session.delete = AsyncMock(return_value=_Response(text="deleted"))
        session.get = AsyncMock(return_value=_Response(text="got"))
        session.post = AsyncMock(return_value=_Response(text="posted"))
        session.put = AsyncMock(return_value=_Response(text="put"))
        client._client_session = session  # pylint: disable=protected-access

        deleted = await client._call_api(
            "path/delete", method=HTTPMethod.DELETE
        )  # pylint: disable=protected-access
        got = await client._call_api(
            "path/get", method=HTTPMethod.GET
        )  # pylint: disable=protected-access
        posted = await client._call_api(  # pylint: disable=protected-access
            "path/post",
            content_type="application/json",
            data={"a": 1},
            method=HTTPMethod.POST,
        )
        form = aiohttp.FormData()
        form.add_field("file", b"x", filename="x.bin")
        put = await client._call_api(
            "path/put", files=form, method=HTTPMethod.PUT
        )  # pylint: disable=protected-access

        self.assertTrue(deleted["ok"])
        self.assertTrue(got["ok"])
        self.assertTrue(posted["ok"])
        self.assertTrue(put["ok"])
        self.assertEqual(deleted["raw"], "deleted")
        self.assertEqual(got["raw"], "got")
        self.assertEqual(posted["raw"], "posted")
        self.assertEqual(put["raw"], "put")
        session.delete.assert_awaited_once()
        session.get.assert_awaited_once()
        session.post.assert_awaited_once()
        session.put.assert_awaited_once()

        post_kwargs = session.post.await_args.kwargs
        self.assertEqual(
            post_kwargs["headers"]["Authorization"],
            "Bearer TOKEN_123",
        )
        self.assertEqual(post_kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(post_kwargs["data"], json.dumps({"a": 1}))

        put_kwargs = session.put.await_args.kwargs
        self.assertIs(put_kwargs["data"], form)

    async def test_call_api_uses_files_factory_and_closes_resources(self) -> None:
        client = self._new_client()
        session = Mock()
        session.post = AsyncMock(return_value=_Response(text="posted"))
        client._client_session = session  # pylint: disable=protected-access
        resource = Mock()

        def files_factory() -> tuple[aiohttp.FormData, list]:
            form = aiohttp.FormData()
            form.add_field("file", b"x", filename="x.bin")
            return form, [resource]

        posted = await client._call_api(  # pylint: disable=protected-access
            "path/post",
            method=HTTPMethod.POST,
            files_factory=files_factory,
        )

        self.assertTrue(posted["ok"])
        resource.close.assert_called_once()

    async def test_call_api_returns_error_when_files_factory_fails(self) -> None:
        client = self._new_client()
        session = Mock()
        session.post = AsyncMock(return_value=_Response(text="posted"))
        client._client_session = session  # pylint: disable=protected-access

        def files_factory() -> tuple[aiohttp.FormData, list]:
            raise OSError("missing-file")

        result = await client._call_api(  # pylint: disable=protected-access
            "path/post",
            method=HTTPMethod.POST,
            files_factory=files_factory,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing-file")
        session.post.assert_not_awaited()
        client._logging_gateway.error.assert_any_call("missing-file")

    async def test_call_api_unknown_method_raises_value_error(self) -> None:
        client = self._new_client()
        session = Mock()
        session.delete = AsyncMock(return_value=_Response(text="deleted"))
        session.get = AsyncMock(return_value=_Response(text="got"))
        session.post = AsyncMock(return_value=_Response(text="posted"))
        session.put = AsyncMock(return_value=_Response(text="put"))
        client._client_session = session  # pylint: disable=protected-access

        with self.assertRaisesRegex(ValueError, "Unsupported HTTP method"):
            await client._call_api(
                "path/patch", method="PATCH"
            )  # pylint: disable=protected-access

    async def test_call_api_handles_connection_error(self) -> None:
        client = self._new_client()
        client._max_api_retries = 0  # pylint: disable=protected-access
        session = Mock()
        session.get = AsyncMock(side_effect=aiohttp.ClientConnectionError("offline"))
        client._client_session = session  # pylint: disable=protected-access

        result = await client._call_api(
            "path/get", method=HTTPMethod.GET
        )  # pylint: disable=protected-access

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "offline")
        client._logging_gateway.error.assert_called_once_with("offline")

    async def test_call_api_requires_initialized_session(self) -> None:
        client = self._new_client()

        result = await client._call_api(
            "path/get", method=HTTPMethod.GET
        )  # pylint: disable=protected-access

        self.assertFalse(result["ok"])
        client._logging_gateway.error.assert_called_once_with(
            "WhatsApp client session is not initialized."
        )

    async def test_call_api_returns_none_for_non_success_status(self) -> None:
        client = self._new_client()
        client._max_api_retries = 0  # pylint: disable=protected-access
        session = Mock()
        session.get = AsyncMock(return_value=_Response(status=401, text="unauthorized"))
        client._client_session = session  # pylint: disable=protected-access

        result = await client._call_api(
            "path/get", method=HTTPMethod.GET
        )  # pylint: disable=protected-access

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 401)
        client._logging_gateway.error.assert_any_call(
            "Graph API call failed (401) for GET path/get."
        )
        client._logging_gateway.error.assert_any_call("unauthorized")

    async def test_call_api_non_success_with_empty_body_logs_once(self) -> None:
        client = self._new_client()
        client._max_api_retries = 0  # pylint: disable=protected-access
        session = Mock()
        session.get = AsyncMock(return_value=_Response(status=500, text=""))
        client._client_session = session  # pylint: disable=protected-access

        result = await client._call_api(
            "path/get", method=HTTPMethod.GET
        )  # pylint: disable=protected-access

        self.assertFalse(result["ok"])
        client._logging_gateway.error.assert_called_once_with(
            "Graph API call failed (500) for GET path/get."
        )

    async def test_call_api_retries_on_retryable_status(self) -> None:
        client = self._new_client()
        client._max_api_retries = 1  # pylint: disable=protected-access
        client._retry_backoff_seconds = 0  # pylint: disable=protected-access
        session = Mock()
        session.get = AsyncMock(
            side_effect=[
                _Response(status=500, text=""),
                _Response(status=200, text='{"id":"ok"}'),
            ]
        )
        client._client_session = session  # pylint: disable=protected-access

        result = await client._call_api(
            "path/get", method=HTTPMethod.GET
        )  # pylint: disable=protected-access

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"id": "ok"})
        self.assertEqual(session.get.await_count, 2)

    async def test_call_api_retries_on_transport_error(self) -> None:
        client = self._new_client()
        client._max_api_retries = 1  # pylint: disable=protected-access
        client._retry_backoff_seconds = 0  # pylint: disable=protected-access
        session = Mock()
        session.get = AsyncMock(
            side_effect=[
                aiohttp.ClientConnectionError("offline"),
                _Response(status=200, text='{"id":"ok"}'),
            ]
        )
        client._client_session = session  # pylint: disable=protected-access

        result = await client._call_api(
            "path/get", method=HTTPMethod.GET
        )  # pylint: disable=protected-access

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"id": "ok"})
        self.assertEqual(session.get.await_count, 2)

    async def test_call_api_success_with_non_dict_json_body_returns_none_data(self) -> None:
        client = self._new_client()
        client._max_api_retries = 0  # pylint: disable=protected-access
        session = Mock()
        session.get = AsyncMock(return_value=_Response(text="[]", status=200))
        client._client_session = session  # pylint: disable=protected-access

        result = await client._call_api("path/get", method=HTTPMethod.GET)  # pylint: disable=protected-access

        self.assertTrue(result["ok"])
        self.assertIsNone(result["data"])

    async def test_call_api_returns_unknown_failure_when_retry_loop_is_skipped(self) -> None:
        client = self._new_client()
        client._max_api_retries = -1  # pylint: disable=protected-access
        client._client_session = Mock()  # pylint: disable=protected-access
        client._client_session.get = AsyncMock(return_value=_Response(status=200, text="{}"))  # pylint: disable=protected-access

        result = await client._call_api("path/get", method=HTTPMethod.GET)  # pylint: disable=protected-access

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Unknown API failure.")
        client._client_session.get.assert_not_awaited()  # pylint: disable=protected-access

    async def test_download_file_http_success_and_fallback_paths(self) -> None:
        client = self._new_client()
        session = Mock()
        successful_response = _Response(status=200, body=b"png-bytes")
        session.get = AsyncMock(return_value=successful_response)
        client._client_session = session  # pylint: disable=protected-access

        saved_path = (
            await client._download_file_http(  # pylint: disable=protected-access
                "https://example.com/file",
                "image/png; charset=utf-8",
            )
        )
        self.assertTrue(os.path.exists(saved_path))
        with open(saved_path, "rb") as fh:
            self.assertEqual(fh.read(), b"png-bytes")
        os.remove(saved_path)
        self.assertTrue(successful_response.release_called)
        self.assertTrue(successful_response.close_called)

        session.get = AsyncMock(return_value=_Response(status=200, body=b"abc"))
        unknown_extension = (
            await client._download_file_http(  # pylint: disable=protected-access
                "https://example.com/file",
                "application/x-unknown-type",
            )
        )
        self.assertIsNone(unknown_extension)

        session.get = AsyncMock(return_value=_Response(status=404, body=b"ignored"))
        not_found = (
            await client._download_file_http(  # pylint: disable=protected-access
                "https://example.com/file",
                "image/png",
            )
        )
        self.assertIsNone(not_found)

    async def test_download_file_http_resolves_mimetype_from_response_headers(
        self,
    ) -> None:
        client = self._new_client()
        session = Mock()
        session.get = AsyncMock(
            return_value=_Response(
                status=200,
                body=b"png-bytes",
                headers={"Content-Type": "image/png; charset=utf-8"},
            )
        )
        client._client_session = session  # pylint: disable=protected-access

        saved_path = await client._download_file_http(  # pylint: disable=protected-access
            "https://example.com/file",
            None,
        )
        self.assertTrue(os.path.exists(saved_path))
        os.remove(saved_path)

    async def test_download_file_http_rejects_missing_mimetype_and_header(self) -> None:
        client = self._new_client()
        session = Mock()
        session.get = AsyncMock(
            return_value=_Response(
                status=200,
                body=b"png-bytes",
            )
        )
        client._client_session = session  # pylint: disable=protected-access

        result = await client._download_file_http(  # pylint: disable=protected-access
            "https://example.com/file",
            None,
        )
        self.assertIsNone(result)
        client._logging_gateway.error.assert_any_call(
            "Media download failed due to missing or unsupported mimetype."
        )

    def test_resolve_media_extension_handles_empty_and_non_mapping_headers(self) -> None:
        client = self._new_client()

        self.assertIsNone(client._normalize_mimetype(" ; charset=utf-8"))  # pylint: disable=protected-access

        response_without_mapping_headers = SimpleNamespace(headers=object())
        self.assertIsNone(
            client._resolve_media_extension(  # pylint: disable=protected-access
                declared_mimetype=None,
                response=response_without_mapping_headers,
            )
        )

    async def test_download_file_http_requires_open_session(self) -> None:
        client = self._new_client()
        closed_session = Mock()
        closed_session.closed = True
        client._client_session = closed_session  # pylint: disable=protected-access

        result = await client._download_file_http(
            "https://example.com/file", "image/png"
        )  # pylint: disable=protected-access

        self.assertIsNone(result)
        client._logging_gateway.error.assert_called_once_with(
            "WhatsApp client session is not initialized."
        )

    async def test_download_file_http_handles_connection_error(self) -> None:
        client = self._new_client()
        session = Mock()
        session.get = AsyncMock(
            side_effect=aiohttp.ClientConnectionError("network-down")
        )
        client._client_session = session  # pylint: disable=protected-access

        result = await client._download_file_http(
            "https://example.com/file", "image/png"
        )  # pylint: disable=protected-access

        self.assertIsNone(result)
        client._logging_gateway.error.assert_called_once_with("network-down")

    async def test_download_file_http_rejects_oversized_media(self) -> None:
        client = self._new_client()
        client._max_download_bytes = 2  # pylint: disable=protected-access
        session = Mock()
        session.get = AsyncMock(return_value=_Response(status=200, body=b"abc"))
        client._client_session = session  # pylint: disable=protected-access

        result = await client._download_file_http(
            "https://example.com/file", "image/png"
        )  # pylint: disable=protected-access

        self.assertIsNone(result)
        client._logging_gateway.error.assert_any_call(
            "Downloaded media exceeded max allowed size."
        )

    async def test_download_file_http_streaming_path_and_stream_limit(self) -> None:
        client = self._new_client()
        session = Mock()
        session.get = AsyncMock(
            return_value=_StreamResponse(status=200, chunks=[b"ab", b"cd"])
        )
        client._client_session = session  # pylint: disable=protected-access

        saved_path = await client._download_file_http(
            "https://example.com/file", "image/png"
        )  # pylint: disable=protected-access
        self.assertTrue(os.path.exists(saved_path))
        with open(saved_path, "rb") as fh:
            self.assertEqual(fh.read(), b"abcd")
        os.remove(saved_path)

        client._max_download_bytes = 2  # pylint: disable=protected-access
        session.get = AsyncMock(
            return_value=_StreamResponse(status=200, chunks=[b"abc"])
        )
        oversized = await client._download_file_http(
            "https://example.com/file", "image/png"
        )  # pylint: disable=protected-access
        self.assertIsNone(oversized)
        client._logging_gateway.error.assert_any_call(
            "Downloaded media exceeded max allowed size."
        )

    async def test_download_file_http_removes_partial_file_on_write_error(self) -> None:
        client = self._new_client()
        session = Mock()
        session.get = AsyncMock(return_value=_Response(status=200, body=b"png-bytes"))
        client._client_session = session  # pylint: disable=protected-access

        fd, temp_path = tempfile.mkstemp(suffix=".png")
        with (
            patch(
                "mugen.core.client.whatsapp.tempfile.mkstemp",
                return_value=(fd, temp_path),
            ),
            patch(
                "mugen.core.client.whatsapp.open",
                side_effect=OSError("disk full"),
            ),
        ):
            result = await client._download_file_http(
                "https://example.com/file", "image/png"
            )  # pylint: disable=protected-access

        self.assertIsNone(result)
        self.assertFalse(os.path.exists(temp_path))

    async def test_managed_http_get_handles_responses_without_release_or_close(self) -> None:
        client = self._new_client()

        class _BareResponse:
            status = 200

            async def read(self) -> bytes:
                return b"ok"

        session = Mock()
        session.get = AsyncMock(return_value=_BareResponse())
        client._client_session = session  # pylint: disable=protected-access

        async with client._managed_http_get("https://example.com/x"):  # pylint: disable=protected-access
            pass

    async def test_send_message_delegates_to_call_api(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(
            return_value={
                "ok": True,
                "status": 200,
                "data": {"messages": [{"id": "sent-id"}]},
                "error": None,
                "raw": '{"messages":[{"id":"sent-id"}]}',
            }
        )  # pylint: disable=protected-access

        result = await client._send_message(
            {"type": "text"}
        )  # pylint: disable=protected-access

        self.assertTrue(result["ok"])
        client._call_api.assert_awaited_once_with(
            path="123456789/messages",
            content_type="application/json",
            data={"type": "text"},
            correlation_id=None,
        )

    async def test_send_message_uses_context_message_id_as_correlation_id(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(return_value={"ok": True})  # pylint: disable=protected-access

        await client._send_message(  # pylint: disable=protected-access
            {
                "type": "text",
                "context": {
                    "message_id": "wamid-context",
                },
            }
        )

        client._call_api.assert_awaited_once_with(
            path="123456789/messages",
            content_type="application/json",
            data={
                "type": "text",
                "context": {
                    "message_id": "wamid-context",
                },
            },
            correlation_id="wamid-context",
        )

    async def test_send_message_ignores_empty_context_message_id(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(return_value={"ok": True})  # pylint: disable=protected-access

        await client._send_message(  # pylint: disable=protected-access
            {
                "type": "text",
                "context": {
                    "message_id": "",
                },
            }
        )

        client._call_api.assert_awaited_once_with(
            path="123456789/messages",
            content_type="application/json",
            data={
                "type": "text",
                "context": {
                    "message_id": "",
                },
            },
            correlation_id=None,
        )

    async def test_send_message_uses_reaction_message_id_as_correlation_id(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(return_value={"ok": True})  # pylint: disable=protected-access

        await client._send_message(  # pylint: disable=protected-access
            {
                "type": "reaction",
                "reaction": {
                    "message_id": "wamid-reaction",
                    "emoji": "👍",
                },
            }
        )

        client._call_api.assert_awaited_once_with(
            path="123456789/messages",
            content_type="application/json",
            data={
                "type": "reaction",
                "reaction": {
                    "message_id": "wamid-reaction",
                    "emoji": "👍",
                },
            },
            correlation_id="wamid-reaction",
        )

    async def test_send_message_ignores_empty_reaction_message_id(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(return_value={"ok": True})  # pylint: disable=protected-access

        await client._send_message(  # pylint: disable=protected-access
            {
                "type": "reaction",
                "reaction": {
                    "message_id": "",
                    "emoji": "👍",
                },
            }
        )

        client._call_api.assert_awaited_once_with(
            path="123456789/messages",
            content_type="application/json",
            data={
                "type": "reaction",
                "reaction": {
                    "message_id": "",
                    "emoji": "👍",
                },
            },
            correlation_id=None,
        )
