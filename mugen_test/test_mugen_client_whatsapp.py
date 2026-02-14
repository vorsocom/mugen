"""Unit tests for mugen.core.client.whatsapp.DefaultWhatsAppClient."""

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
            ),
            business=SimpleNamespace(phone_number_id="123456789"),
        )
    )


class _Response:
    def __init__(self, *, text: str = "", status: int = 200, body: bytes = b""):
        self._text = text
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._body


class _FakeTempFileContext:
    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _ = (exc_type, exc_val, exc_tb)
        return False


class _FakeAsyncFileContext:
    def __init__(self, path: str):
        self._path = path
        self._fh = None

    async def __aenter__(self):
        self._fh = open(self._path, "wb")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        _ = (exc_type, exc_val, exc_tb)
        self._fh.close()
        return False

    async def write(self, data: bytes):
        self._fh.write(data)


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

        with patch(
            "mugen.core.client.whatsapp.aiohttp.ClientSession",
            return_value=fake_session,
        ):
            await client.init()

        await client.close()
        client._logging_gateway.debug.assert_any_call("DefaultWhatsAppClient.init")
        client._logging_gateway.debug.assert_any_call("DefaultWhatsAppClient.close")
        fake_session.close.assert_awaited_once()

    async def test_api_wrapper_methods_delegate_to_internal_helpers(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(
            return_value="ok"
        )  # pylint: disable=protected-access
        client._download_file_http = AsyncMock(  # pylint: disable=protected-access
            return_value="/tmp/file.png"
        )

        self.assertEqual(await client.delete_media("media-id"), "ok")
        self.assertEqual(await client.retrieve_media_url("media-id"), "ok")
        self.assertEqual(
            await client.download_media("https://example.com/x", "image/png"),
            "/tmp/file.png",
        )
        client._call_api.assert_any_await("media-id", method=HTTPMethod.DELETE)
        client._call_api.assert_any_await("media-id", method=HTTPMethod.GET)
        client._download_file_http.assert_awaited_once_with(
            "https://example.com/x", "image/png"
        )

    async def test_send_message_payload_builders(self) -> None:
        client = self._new_client()
        client._send_message = AsyncMock(
            return_value="sent"
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
            self.assertEqual(result, "sent")
            data = client._send_message.await_args.kwargs["data"]
            self.assertEqual(data["type"], msg_type)
            self.assertEqual(data["to"], "+15550001")
            self.assertEqual(data[payload_key], payload)
            self.assertEqual(data["context"], {"message_id": "msg-1"})

            result_no_reply = await method(payload, "15550001")
            self.assertEqual(result_no_reply, "sent")
            data_no_reply = client._send_message.await_args.kwargs["data"]
            self.assertEqual(data_no_reply["type"], msg_type)
            self.assertNotIn("context", data_no_reply)

        text_result = await client.send_text_message(
            "hello", "15550002", reply_to="msg-2"
        )
        self.assertEqual(text_result, "sent")
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
        self.assertEqual(reaction_result, "sent")
        reaction_data = client._send_message.await_args.kwargs["data"]
        self.assertEqual(reaction_data["type"], "reaction")
        self.assertEqual(reaction_data["reaction"], {"emoji": "👍"})

    async def test_upload_media_bytesio_and_file_path(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(
            return_value="media-id"
        )  # pylint: disable=protected-access

        uploaded_from_bytes = await client.upload_media(BytesIO(b"abc"), "image/png")
        self.assertEqual(uploaded_from_bytes, "media-id")
        first_call = client._call_api.await_args
        self.assertEqual(first_call.args[0], "123456789/media")
        self.assertIsInstance(first_call.kwargs["files"], aiohttp.FormData)

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"hello")
            path = tf.name
        try:
            uploaded_from_file = await client.upload_media(path, "text/plain")
            self.assertEqual(uploaded_from_file, "media-id")
            second_call = client._call_api.await_args
            self.assertEqual(second_call.args[0], "123456789/media")
            self.assertIsInstance(second_call.kwargs["files"], aiohttp.FormData)
        finally:
            os.remove(path)

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

        self.assertEqual(
            (deleted, got, posted, put), ("deleted", "got", "posted", "put")
        )
        session.delete.assert_awaited_once()
        session.get.assert_awaited_once()
        session.post.assert_awaited_once()
        session.put.assert_awaited_once()

        post_kwargs = session.post.await_args.kwargs
        self.assertEqual(
            post_kwargs["headers"]["Authorization"],
            "Bearer TOKEN_123",
        )
        self.assertEqual(post_kwargs["headers"]["Content-type"], "application/json")
        self.assertEqual(post_kwargs["data"], json.dumps({"a": 1}))

        put_kwargs = session.put.await_args.kwargs
        self.assertIs(put_kwargs["data"], form)

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
        session = Mock()
        session.get = AsyncMock(side_effect=aiohttp.ClientConnectionError("offline"))
        client._client_session = session  # pylint: disable=protected-access

        result = await client._call_api(
            "path/get", method=HTTPMethod.GET
        )  # pylint: disable=protected-access

        self.assertIsNone(result)
        client._logging_gateway.error.assert_called_once_with("offline")

    async def test_download_file_http_success_and_fallback_paths(self) -> None:
        client = self._new_client()
        session = Mock()
        session.get = AsyncMock(return_value=_Response(status=200, body=b"png-bytes"))
        client._client_session = session  # pylint: disable=protected-access

        fd, expected_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        with (
            patch(
                "mugen.core.client.whatsapp.tempfile.NamedTemporaryFile",
                return_value=_FakeTempFileContext(expected_path),
            ),
            patch(
                "mugen.core.client.whatsapp.aiofiles.open",
                side_effect=lambda path, _mode, **_kwargs: _FakeAsyncFileContext(path),
            ),
        ):
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

    async def test_send_message_delegates_to_call_api(self) -> None:
        client = self._new_client()
        client._call_api = AsyncMock(
            return_value="sent-id"
        )  # pylint: disable=protected-access

        result = await client._send_message(
            {"type": "text"}
        )  # pylint: disable=protected-access

        self.assertEqual(result, "sent-id")
        client._call_api.assert_awaited_once_with(
            path="123456789/messages",
            content_type="application/json",
            data={"type": "text"},
        )
