"""Unit tests for mugen.core.plugin.web.api.chat."""

from inspect import unwrap
import os
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.web.api import chat


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


class _AwaitableValue:
    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _inner():
            return self._value

        return _inner().__await__()


class _DummyUpload:
    def __init__(
        self,
        *,
        mimetype: str,
        content_length: int | None,
        filename: str,
        payload_bytes: bytes,
    ) -> None:
        self.mimetype = mimetype
        self.content_length = content_length
        self.filename = filename
        self._payload_bytes = payload_bytes

    async def save(self, path: str) -> None:
        with open(path, "wb") as handle:
            handle.write(self._payload_bytes)


def _make_config(*, basedir: str, max_upload: int = 1024) -> SimpleNamespace:
    return SimpleNamespace(
        basedir=basedir,
        web=SimpleNamespace(
            media=SimpleNamespace(
                storage=SimpleNamespace(path="web_media"),
                max_upload_bytes=max_upload,
                allowed_mimetypes=["image/*", "application/*"],
            )
        ),
    )


class TestMugenWebApiChat(unittest.IsolatedAsyncioTestCase):
    """Covers web chat endpoint validation and branch behavior."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
            web_client="web-client",
        )

        with patch.object(chat.di, "container", new=container):
            self.assertEqual(chat._config_provider(), "cfg")
            self.assertEqual(chat._logger_provider(), "logger")
            self.assertEqual(chat._web_client_provider(), "web-client")

    async def test_helper_branch_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(basedir=tmpdir, max_upload=128)

            self.assertTrue(
                chat._resolve_media_storage_path(config).endswith("web_media")
            )
            config.web.media.storage.path = "/tmp/abs-media"
            self.assertEqual(chat._resolve_media_storage_path(config), "/tmp/abs-media")

            no_basedir_config = SimpleNamespace(
                web=SimpleNamespace(media=SimpleNamespace(storage=SimpleNamespace(path="rel")))
            )
            self.assertTrue(chat._resolve_media_storage_path(no_basedir_config).endswith("rel"))

            wc = SimpleNamespace(media_max_upload_bytes="256")
            self.assertEqual(chat._resolve_media_max_upload_bytes(config, wc), 256)
            wc = SimpleNamespace(media_max_upload_bytes="bad")
            self.assertEqual(chat._resolve_media_max_upload_bytes(config, wc), 128)
            wc = SimpleNamespace(media_max_upload_bytes=0)
            self.assertEqual(chat._resolve_media_max_upload_bytes(config, wc), 128)
            config.web.media.max_upload_bytes = "bad"
            self.assertEqual(
                chat._resolve_media_max_upload_bytes(config, SimpleNamespace()),
                chat._DEFAULT_MEDIA_MAX_UPLOAD_BYTES,
            )
            config.web.media.max_upload_bytes = -1
            self.assertEqual(
                chat._resolve_media_max_upload_bytes(config, SimpleNamespace()),
                chat._DEFAULT_MEDIA_MAX_UPLOAD_BYTES,
            )

            wc = SimpleNamespace(media_allowed_mimetypes=[" image/* ", 123, ""])
            self.assertEqual(chat._resolve_media_allowed_mimetypes(config, wc), ["image/*"])
            config.web.media.allowed_mimetypes = "bad"
            self.assertEqual(
                chat._resolve_media_allowed_mimetypes(config, SimpleNamespace()),
                chat._DEFAULT_MEDIA_ALLOWED_MIMETYPES,
            )
            config.web.media.allowed_mimetypes = [123, ""]
            self.assertEqual(
                chat._resolve_media_allowed_mimetypes(config, SimpleNamespace()),
                chat._DEFAULT_MEDIA_ALLOWED_MIMETYPES,
            )
            self.assertEqual(
                chat._resolve_media_allowed_mimetypes(
                    config,
                    SimpleNamespace(media_allowed_mimetypes=[123, ""]),
                ),
                chat._DEFAULT_MEDIA_ALLOWED_MIMETYPES,
            )

            self.assertEqual(
                chat._resolve_config_value(config, ("web", "missing"), "x"),
                "x",
            )
            self.assertFalse(
                chat._mimetype_allowed(
                    "",
                    allowed_mimetypes=["image/*"],
                    web_client=SimpleNamespace(),
                )
            )
            self.assertTrue(
                chat._mimetype_allowed(
                    "image/png",
                    allowed_mimetypes=["image/*"],
                    web_client=SimpleNamespace(),
                )
            )
            self.assertTrue(
                chat._mimetype_allowed(
                    "application/json",
                    allowed_mimetypes=["image/*"],
                    web_client=SimpleNamespace(
                        mimetype_allowed=lambda _: True,
                    ),
                )
            )

            bogus_path = os.path.join(tmpdir, "missing.file")
            chat._remove_file_if_exists(bogus_path)
            self.assertFalse(os.path.exists(bogus_path))
            existing_path = os.path.join(tmpdir, "existing.file")
            with open(existing_path, "wb") as handle:
                handle.write(b"x")
            with patch("mugen.core.plugin.web.api.chat.os.remove", side_effect=OSError()):
                chat._remove_file_if_exists(existing_path)
            self.assertEqual(chat._normalize_message_type("TEXT"), "text")
            with self.assertRaises(ValueError):
                chat._normalize_message_type(None)
            with self.assertRaises(ValueError):
                chat._normalize_message_type("")
            with self.assertRaises(ValueError):
                chat._normalize_message_type("unsupported")
            self.assertEqual(chat._normalize_client_message_id(" c-1 "), "c-1")
            with self.assertRaises(ValueError):
                chat._normalize_client_message_id(None)
            with self.assertRaises(ValueError):
                chat._normalize_client_message_id("")

            self.assertIsNone(chat._parse_metadata(None))
            with self.assertRaises(ValueError):
                chat._parse_metadata(1)
            with self.assertRaises(ValueError):
                chat._parse_metadata("{bad")
            with self.assertRaises(ValueError):
                chat._parse_metadata("[]")

    async def test_messages_create_happy_path_with_text(self) -> None:
        endpoint = unwrap(chat.web_messages_create)
        web_client = SimpleNamespace(enqueue_message=AsyncMock(return_value={"job_id": "j1"}))

        request_obj = SimpleNamespace(
            form=_AwaitableValue(
                {
                    "conversation_id": "conv-1",
                    "message_type": "text",
                    "text": "hello",
                    "client_message_id": "c1",
                    "metadata": '{"k":"v"}',
                }
            ),
            files=_AwaitableValue({}),
        )

        fake_response = SimpleNamespace(status_code=200)
        with (
            patch.object(chat, "request", new=request_obj),
            patch.object(chat, "jsonify", return_value=fake_response),
        ):
            response, status = await endpoint(
                auth_user="user-1",
                config_provider=lambda: _make_config(basedir=tempfile.gettempdir()),
                logger_provider=lambda: Mock(),
                web_client_provider=lambda: web_client,
            )

        self.assertEqual(status, 202)
        web_client.enqueue_message.assert_awaited_once()
        kwargs = web_client.enqueue_message.await_args.kwargs
        self.assertEqual(kwargs["auth_user"], "user-1")
        self.assertEqual(kwargs["conversation_id"], "conv-1")
        self.assertEqual(kwargs["message_type"], "text")
        self.assertEqual(kwargs["metadata"], {"k": "v"})
        self.assertEqual(response.status_code, 200)

    async def test_messages_create_requires_client_message_id(self) -> None:
        endpoint = unwrap(chat.web_messages_create)
        base_form = {
            "conversation_id": "conv-1",
            "message_type": "text",
            "text": "hello",
        }
        invalid_forms = [
            dict(base_form),
            {**base_form, "client_message_id": " "},
            {**base_form, "client_message_id": 123},
        ]

        for form in invalid_forms:
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(form),
                        files=_AwaitableValue({}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="user-1",
                        config_provider=lambda: _make_config(basedir=tempfile.gettempdir()),
                        logger_provider=lambda: Mock(),
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)
                self.assertEqual(ex.exception.message, "client_message_id is required")

    async def test_messages_create_validation_and_error_paths(self) -> None:
        endpoint = unwrap(chat.web_messages_create)
        logger = Mock()
        web_client = SimpleNamespace(enqueue_message=AsyncMock())

        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
            patch.object(
                chat,
                "request",
                new=SimpleNamespace(
                    form=_AwaitableValue({"message_type": "text", "text": "hello"}),
                    files=_AwaitableValue({}),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    auth_user="user-1",
                    config_provider=lambda: _make_config(basedir=tempfile.gettempdir()),
                    logger_provider=lambda: logger,
                    web_client_provider=lambda: web_client,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
            patch.object(
                chat,
                "request",
                new=SimpleNamespace(
                    form=_AwaitableValue(
                        {
                            "conversation_id": "conv-1",
                            "message_type": "text",
                            "client_message_id": "c-metadata",
                            "text": "hello",
                            "metadata": "not-json",
                        }
                    ),
                    files=_AwaitableValue({}),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    auth_user="user-1",
                    config_provider=lambda: _make_config(basedir=tempfile.gettempdir()),
                    logger_provider=lambda: logger,
                    web_client_provider=lambda: web_client,
                )
            self.assertEqual(ex.exception.code, 400)

        web_client.enqueue_message = AsyncMock(side_effect=PermissionError())
        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
            patch.object(
                chat,
                "request",
                new=SimpleNamespace(
                    form=_AwaitableValue(
                        {
                            "conversation_id": "conv-1",
                            "message_type": "text",
                            "client_message_id": "c-permission",
                            "text": "hello",
                        }
                    ),
                    files=_AwaitableValue({}),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    auth_user="user-1",
                    config_provider=lambda: _make_config(basedir=tempfile.gettempdir()),
                    logger_provider=lambda: logger,
                    web_client_provider=lambda: web_client,
                )
            self.assertEqual(ex.exception.code, 403)

        web_client.enqueue_message = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
            patch.object(
                chat,
                "request",
                new=SimpleNamespace(
                    form=_AwaitableValue(
                        {
                            "conversation_id": "conv-1",
                            "message_type": "text",
                            "client_message_id": "c-runtime",
                            "text": "hello",
                        }
                    ),
                    files=_AwaitableValue({}),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    auth_user="user-1",
                    config_provider=lambda: _make_config(basedir=tempfile.gettempdir()),
                    logger_provider=lambda: logger,
                    web_client_provider=lambda: web_client,
                )
            self.assertEqual(ex.exception.code, 500)
            logger.exception.assert_called()

    async def test_messages_create_media_validation(self) -> None:
        endpoint = unwrap(chat.web_messages_create)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(basedir=tmpdir, max_upload=8)
            web_client = SimpleNamespace(enqueue_message=AsyncMock(return_value={"job_id": "j1"}))

            disallowed_upload = _DummyUpload(
                mimetype="audio/ogg",
                content_length=4,
                filename="sample.ogg",
                payload_bytes=b"1234",
            )
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "conv-1",
                                "message_type": "file",
                                "client_message_id": "c-file-1",
                            }
                        ),
                        files=_AwaitableValue({"file": disallowed_upload}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="user-1",
                        config_provider=lambda: config,
                        logger_provider=lambda: Mock(),
                        web_client_provider=lambda: web_client,
                    )
                self.assertEqual(ex.exception.code, 415)

            oversized_upload = _DummyUpload(
                mimetype="image/png",
                content_length=10,
                filename="sample.png",
                payload_bytes=b"1234567890",
            )
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "conv-1",
                                "message_type": "image",
                                "client_message_id": "c-image-1",
                            }
                        ),
                        files=_AwaitableValue({"file": oversized_upload}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="user-1",
                        config_provider=lambda: config,
                        logger_provider=lambda: Mock(),
                        web_client_provider=lambda: web_client,
                    )
                self.assertEqual(ex.exception.code, 413)

    async def test_messages_create_additional_error_branches(self) -> None:
        endpoint = unwrap(chat.web_messages_create)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(basedir=tmpdir, max_upload=8)
            logger = Mock()

            # Unsupported message_type branch.
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "c1",
                                "message_type": "bad-type",
                                "client_message_id": "c-bad-type",
                            }
                        ),
                        files=_AwaitableValue({}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="u1",
                        config_provider=lambda: config,
                        logger_provider=lambda: logger,
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

            # Missing text for text message.
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "c1",
                                "message_type": "text",
                                "client_message_id": "c-missing-text",
                            }
                        ),
                        files=_AwaitableValue({}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="u1",
                        config_provider=lambda: config,
                        logger_provider=lambda: logger,
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

            # Missing file for media message.
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "c1",
                                "message_type": "image",
                                "client_message_id": "c-missing-file",
                            }
                        ),
                        files=_AwaitableValue({}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="u1",
                        config_provider=lambda: config,
                        logger_provider=lambda: logger,
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

            # File not allowed for text message.
            upload = _DummyUpload(
                mimetype="image/png",
                content_length=4,
                filename="x.png",
                payload_bytes=b"1234",
            )
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "c1",
                                "message_type": "text",
                                "client_message_id": "c-text-with-file",
                                "text": "ok",
                            }
                        ),
                        files=_AwaitableValue({"file": upload}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="u1",
                        config_provider=lambda: config,
                        logger_provider=lambda: logger,
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
                self.assertEqual(ex.exception.code, 400)

            # Actual size exceeds max after save (post-write size check branch).
            oversized_after_save = _DummyUpload(
                mimetype="image/png",
                content_length=4,
                filename="x.png",
                payload_bytes=b"123456789",
            )
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "c2",
                                "message_type": "image",
                                "client_message_id": "c-post-size",
                            }
                        ),
                        files=_AwaitableValue({"file": oversized_after_save}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="u1",
                        config_provider=lambda: config,
                        logger_provider=lambda: logger,
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
                self.assertEqual(ex.exception.code, 413)

            # OSError while reading file size.
            upload_getsize_error = _DummyUpload(
                mimetype="image/png",
                content_length=4,
                filename="x.png",
                payload_bytes=b"1234",
            )
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch("mugen.core.plugin.web.api.chat.os.path.getsize", side_effect=OSError()),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "c3",
                                "message_type": "image",
                                "client_message_id": "c-getsize-error",
                            }
                        ),
                        files=_AwaitableValue({"file": upload_getsize_error}),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="u1",
                        config_provider=lambda: config,
                        logger_provider=lambda: logger,
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
                self.assertEqual(ex.exception.code, 500)

            for expected_code, side_effect in (
                (429, OverflowError()),
                (400, ValueError("bad enqueue")),
            ):
                upload_ok = _DummyUpload(
                    mimetype="image/png",
                    content_length=4,
                    filename="x.png",
                    payload_bytes=b"1234",
                )
                with (
                    patch.object(chat, "abort", side_effect=_abort_raiser),
                    patch.object(
                        chat,
                        "request",
                        new=SimpleNamespace(
                            form=_AwaitableValue(
                                {
                                    "conversation_id": "c4",
                                    "message_type": "image",
                                    "client_message_id": "c-enqueue-error",
                                }
                            ),
                            files=_AwaitableValue({"file": upload_ok}),
                        ),
                    ),
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await endpoint(
                            auth_user="u1",
                            config_provider=lambda: config,
                            logger_provider=lambda: logger,
                            web_client_provider=lambda: SimpleNamespace(
                                enqueue_message=AsyncMock(side_effect=side_effect)
                            ),
                    )
                    self.assertEqual(ex.exception.code, expected_code)

            # extension length > 16 branch and non-string filename branch.
            upload_long_ext = _DummyUpload(
                mimetype="image/png",
                content_length=4,
                filename="name.12345678901234567",
                payload_bytes=b"1234",
            )
            upload_none_name = _DummyUpload(
                mimetype="image/png",
                content_length=4,
                filename=None,  # type: ignore[arg-type]
                payload_bytes=b"1234",
            )
            for upload_variant in (upload_long_ext, upload_none_name):
                with (
                    patch.object(chat, "abort", side_effect=_abort_raiser),
                    patch.object(
                        chat,
                        "request",
                        new=SimpleNamespace(
                            form=_AwaitableValue(
                                {
                                    "conversation_id": "c5",
                                    "message_type": "image",
                                    "client_message_id": "c-long-ext",
                                }
                            ),
                            files=_AwaitableValue({"file": upload_variant}),
                        ),
                    ),
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await endpoint(
                            auth_user="u1",
                            config_provider=lambda: config,
                            logger_provider=lambda: logger,
                            web_client_provider=lambda: SimpleNamespace(
                                enqueue_message=AsyncMock(side_effect=OverflowError())
                            ),
                        )
                    self.assertEqual(ex.exception.code, 429)

    async def test_events_stream_uses_last_event_id_header_precedence(self) -> None:
        endpoint = unwrap(chat.web_events_stream)

        async def _stream():
            yield "id: 1\nevent: ack\ndata: {}\n\n"

        web_client = SimpleNamespace(stream_events=AsyncMock(return_value=_stream()))

        request_obj = SimpleNamespace(
            args={"conversation_id": "conv-1", "last_event_id": "3"},
            headers={"Last-Event-ID": "5"},
        )

        with patch.object(chat, "request", new=request_obj):
            response = await endpoint(
                auth_user="user-1",
                logger_provider=lambda: Mock(),
                web_client_provider=lambda: web_client,
            )

        self.assertEqual(response.mimetype, "text/event-stream")
        web_client.stream_events.assert_awaited_once()
        self.assertEqual(
            web_client.stream_events.await_args.kwargs["last_event_id"],
            "5",
        )

    async def test_events_stream_error_paths(self) -> None:
        endpoint = unwrap(chat.web_events_stream)
        logger = Mock()

        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
            patch.object(
                chat,
                "request",
                new=SimpleNamespace(args={}, headers={}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    auth_user="user-1",
                    logger_provider=lambda: logger,
                    web_client_provider=lambda: SimpleNamespace(
                        stream_events=AsyncMock()
                    ),
                )
            self.assertEqual(ex.exception.code, 400)

        for expected_code, side_effect in (
            (403, PermissionError()),
            (404, KeyError("missing")),
            (400, ValueError("bad")),
            (500, RuntimeError("boom")),
        ):
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        args={"conversation_id": "conv-1"},
                        headers={},
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="user-1",
                        logger_provider=lambda: logger,
                        web_client_provider=lambda: SimpleNamespace(
                            stream_events=AsyncMock(side_effect=side_effect)
                        ),
                    )
                self.assertEqual(ex.exception.code, expected_code)

    async def test_media_download_paths(self) -> None:
        endpoint = unwrap(chat.web_media_download)

        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    token="tok",
                    auth_user="user-1",
                    web_client_provider=lambda: SimpleNamespace(
                        resolve_media_download=AsyncMock(return_value=None)
                    ),
                )
            self.assertEqual(ex.exception.code, 404)

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "payload.bin")
            with open(file_path, "wb") as handle:
                handle.write(b"abc")

            with patch.object(chat, "send_file", new=AsyncMock(return_value="ok")) as send_file:
                response = await endpoint(
                    token="tok",
                    auth_user="user-1",
                    web_client_provider=lambda: SimpleNamespace(
                        resolve_media_download=AsyncMock(
                            return_value={
                                "file_path": file_path,
                                "mime_type": "application/octet-stream",
                                "filename": "payload.bin",
                            }
                        )
                    ),
                )

            self.assertEqual(response, "ok")
            send_file.assert_awaited_once()
            self.assertEqual(send_file.await_args.args[0], file_path)

        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    token="tok",
                    auth_user="user-1",
                    web_client_provider=lambda: SimpleNamespace(
                        resolve_media_download=AsyncMock(
                            return_value={"file_path": "/missing/file"}
                        )
                    ),
                )
            self.assertEqual(ex.exception.code, 404)
