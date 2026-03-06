"""Unit tests for mugen.core.plugin.web.api.chat."""

from inspect import unwrap
import json
import os
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.client.web import WebConversationTenantConflictError
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


def _make_config(
    *,
    basedir: str,
    max_upload: int = 1024,
    max_attachments: int = 10,
) -> SimpleNamespace:
    return SimpleNamespace(
        basedir=basedir,
        web=SimpleNamespace(
            media=SimpleNamespace(
                storage=SimpleNamespace(path="web_media"),
                max_upload_bytes=max_upload,
                max_attachments_per_message=max_attachments,
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

            wc = SimpleNamespace(media_max_attachments_per_message="4")
            self.assertEqual(
                chat._resolve_media_max_attachments_per_message(config, wc),
                4,
            )
            wc = SimpleNamespace(media_max_attachments_per_message=0)
            self.assertEqual(
                chat._resolve_media_max_attachments_per_message(config, wc),
                10,
            )
            wc = SimpleNamespace(media_max_attachments_per_message="bad")
            self.assertEqual(
                chat._resolve_media_max_attachments_per_message(config, wc),
                10,
            )
            config.web.media.max_attachments_per_message = "bad"
            self.assertEqual(
                chat._resolve_media_max_attachments_per_message(
                    config,
                    SimpleNamespace(),
                ),
                chat._DEFAULT_MEDIA_MAX_ATTACHMENTS_PER_MESSAGE,
            )
            config.web.media.max_attachments_per_message = 0
            self.assertEqual(
                chat._resolve_media_max_attachments_per_message(
                    config,
                    SimpleNamespace(),
                ),
                chat._DEFAULT_MEDIA_MAX_ATTACHMENTS_PER_MESSAGE,
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
            chat._remove_files_if_exist([bogus_path, existing_path])
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

            self.assertEqual(chat._mapping_keys({"a": 1}), {"a"})
            class _KeysOnly:
                def keys(self):
                    return ["k1", 2]

            self.assertEqual(chat._mapping_keys(_KeysOnly()), {"k1"})
            self.assertEqual(chat._mapping_keys(SimpleNamespace()), set())
            self.assertEqual(chat._iter_file_items({"files[a]": "x"}), [("files[a]", "x")])

            class _MultiFiles:
                def keys(self):
                    return ["files[a]"]

                def items(self, multi=False):
                    if multi:
                        return [("files[a]", "x")]
                    return [("files[a]", "y")]

            self.assertEqual(chat._iter_file_items(_MultiFiles()), [("files[a]", "x")])
            class _ItemsNoMulti:
                def items(self):
                    return [("files[a]", "z")]

            self.assertEqual(chat._iter_file_items(_ItemsNoMulti()), [("files[a]", "z")])
            self.assertEqual(chat._iter_file_items(SimpleNamespace()), [])
            self.assertTrue(chat._structured_payload_present({"parts": "[]"}, {}))
            self.assertFalse(chat._structured_payload_present({}, {}))
            self.assertTrue(chat._legacy_payload_present({"message_type": "text"}, {}))
            self.assertFalse(chat._legacy_payload_present({}, {}))

            self.assertEqual(
                chat._normalize_composition_mode("message_with_attachments"),
                "message_with_attachments",
            )
            with self.assertRaises(chat._StructuredPayloadError):
                chat._normalize_composition_mode(None)
            with self.assertRaises(chat._StructuredPayloadError):
                chat._normalize_composition_mode("")
            with self.assertRaises(chat._StructuredPayloadError):
                chat._normalize_composition_mode("bad-mode")
            with self.assertRaises(chat._StructuredPayloadError):
                chat._parse_structured_parts(None)
            with self.assertRaises(chat._StructuredPayloadError):
                chat._parse_structured_parts("")
            with self.assertRaises(chat._StructuredPayloadError):
                chat._parse_structured_parts("not-json")
            with self.assertRaises(chat._StructuredPayloadError):
                chat._parse_structured_parts("{}")
            with self.assertRaises(chat._StructuredPayloadError):
                chat._parse_structured_parts('[{"type":1}]')
            with self.assertRaises(chat._StructuredPayloadError):
                chat._parse_structured_parts("[1]")
            with self.assertRaises(chat._StructuredPayloadError):
                chat._parse_structured_parts('[{"type":"bad"}]')
            parsed_parts = chat._parse_structured_parts('[{"type":"text"}]')
            self.assertEqual(parsed_parts[0]["text"], "")
            parsed_attachment_parts = chat._parse_structured_parts(
                '[{"type":"attachment","id":"a1"}]'
            )
            self.assertEqual(parsed_attachment_parts[0]["metadata"], {})
            parsed_attachment_with_metadata = chat._parse_structured_parts(
                '[{"type":"attachment","id":"a1","metadata":{"k":"v"}}]'
            )
            self.assertEqual(
                parsed_attachment_with_metadata[0]["metadata"],
                {"k": "v"},
            )
            with self.assertRaises(chat._StructuredPayloadError):
                chat._parse_structured_parts(
                    '[{"type":"attachment","id":"a1","metadata":"bad"}]'
                )
            with self.assertRaises(chat._StructuredPayloadError):
                chat._normalize_structured_uploads({"bad": object()})
            with self.assertRaises(chat._StructuredPayloadError):
                chat._normalize_structured_uploads({"files[]": object()})
            class _DuplicateStructuredUploads:
                def items(self, multi=False):
                    if multi:
                        return [("files[a1]", object()), ("files[a1]", object())]
                    return [("files[a1]", object())]

            with self.assertRaises(chat._StructuredPayloadError):
                chat._normalize_structured_uploads(_DuplicateStructuredUploads())
            self.assertEqual(chat._infer_upload_extension("f.txt"), ".txt")
            self.assertEqual(chat._infer_upload_extension("x." + ("1" * 20)), "")
            self.assertEqual(chat._infer_upload_extension(None), "")

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
        self.assertIsNone(kwargs["tenant_slug"])
        self.assertEqual(kwargs["message_type"], "text")
        self.assertEqual(kwargs["metadata"], {"k": "v"})
        self.assertEqual(response.status_code, 200)

    async def test_messages_create_tenant_slug_paths(self) -> None:
        endpoint = unwrap(chat.web_messages_create)
        logger = Mock()
        base_form = {
            "conversation_id": "conv-tenant",
            "message_type": "text",
            "text": "hello",
            "client_message_id": "c-tenant",
        }

        web_client = SimpleNamespace(enqueue_message=AsyncMock(return_value={"job_id": "j1"}))
        with (
            patch.object(
                chat,
                "request",
                new=SimpleNamespace(
                    form=_AwaitableValue(
                        {
                            **base_form,
                            "tenant_slug": "tenant-a",
                        }
                    ),
                    files=_AwaitableValue({}),
                ),
            ),
            patch.object(chat, "jsonify", return_value=SimpleNamespace(status_code=200)),
        ):
            _response, status = await endpoint(
                auth_user="user-1",
                config_provider=lambda: _make_config(basedir=tempfile.gettempdir()),
                logger_provider=lambda: logger,
                web_client_provider=lambda: web_client,
            )
        self.assertEqual(status, 202)
        self.assertEqual(
            web_client.enqueue_message.await_args.kwargs["tenant_slug"],
            "tenant-a",
        )

        for bad_value in ["", "  "]:
            with self.subTest(bad_value=bad_value):
                with (
                    patch.object(chat, "abort", side_effect=_abort_raiser),
                    patch.object(
                        chat,
                        "request",
                        new=SimpleNamespace(
                            form=_AwaitableValue(
                                {
                                    **base_form,
                                    "tenant_slug": bad_value,
                                }
                            ),
                            files=_AwaitableValue({}),
                        ),
                    ),
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await endpoint(
                            auth_user="user-1",
                            config_provider=lambda: _make_config(
                                basedir=tempfile.gettempdir()
                            ),
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
                            **base_form,
                            "tenant_slug": 123,
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

        web_client.enqueue_message = AsyncMock(side_effect=ValueError("invalid tenant_slug"))
        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
            patch.object(
                chat,
                "request",
                new=SimpleNamespace(
                    form=_AwaitableValue(
                        {
                            **base_form,
                            "tenant_slug": "bad-tenant",
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
                            **base_form,
                            "tenant_slug": "tenant-a",
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

        web_client.enqueue_message = AsyncMock(
            side_effect=WebConversationTenantConflictError("conversation tenant mismatch")
        )
        with (
            patch.object(chat, "abort", side_effect=_abort_raiser),
            patch.object(
                chat,
                "request",
                new=SimpleNamespace(
                    form=_AwaitableValue(
                        {
                            **base_form,
                            "tenant_slug": "tenant-a",
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
            self.assertEqual(ex.exception.code, 409)

    async def test_structured_upload_helper_error_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(basedir=tmpdir, max_upload=4)
            web_client = SimpleNamespace(mimetype_allowed=lambda _: True)

            with (
                patch(
                    "mugen.core.plugin.web.api.chat.os.path.getsize",
                    side_effect=OSError(),
                ),
            ):
                with self.assertRaises(chat._StructuredPayloadError) as ex:
                    await chat._persist_structured_upload(
                        uploaded_file=_DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="a.png",
                            payload_bytes=b"1234",
                        ),
                        config=config,
                        web_client=web_client,
                        max_upload_bytes=4,
                        allowed_mimetypes=["image/*"],
                    )
                self.assertEqual(ex.exception.status_code, 500)

            with self.assertRaises(chat._StructuredPayloadError) as ex:
                await chat._persist_structured_upload(
                    uploaded_file=_DummyUpload(
                        mimetype="image/png",
                        content_length=1,
                        filename="a.png",
                        payload_bytes=b"12345",
                    ),
                    config=config,
                    web_client=web_client,
                    max_upload_bytes=4,
                    allowed_mimetypes=["image/*"],
                )
            self.assertEqual(ex.exception.status_code, 413)

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
            logger.error.assert_called_once_with("Failed to enqueue web message: boom")

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

    async def test_messages_create_structured_happy_paths(self) -> None:
        endpoint = unwrap(chat.web_messages_create)
        fake_response = SimpleNamespace(status_code=200)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(basedir=tmpdir, max_upload=128, max_attachments=10)
            web_client = SimpleNamespace(enqueue_message=AsyncMock(return_value={"job_id": "j1"}))

            scenarios = [
                (
                    # C1 text only
                    {
                        "conversation_id": "conv-c1",
                        "client_message_id": "cid-c1",
                        "metadata": '{"source":"c1"}',
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps([{"type": "text", "text": "hello"}]),
                    },
                    {},
                    "message_with_attachments",
                ),
                (
                    # C3 one attachment with caption
                    {
                        "conversation_id": "conv-c3",
                        "client_message_id": "cid-c3",
                        "composition_mode": "attachment_with_caption",
                        "parts": json.dumps(
                            [{"type": "attachment", "id": "a1", "caption": "cap-1"}]
                        ),
                    },
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="img.png",
                            payload_bytes=b"1234",
                        )
                    },
                    "attachment_with_caption",
                ),
                (
                    # C6/C7 multiple attachments
                    {
                        "conversation_id": "conv-c6",
                        "client_message_id": "cid-c6",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps(
                            [
                                {"type": "attachment", "id": "a1"},
                                {"type": "attachment", "id": "a2", "caption": "cap-2"},
                            ]
                        ),
                    },
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="application/pdf",
                            content_length=4,
                            filename="f1.pdf",
                            payload_bytes=b"abcd",
                        ),
                        "files[a2]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f2.png",
                            payload_bytes=b"wxyz",
                        ),
                    },
                    "message_with_attachments",
                ),
                (
                    # C8/C9 text + attachments
                    {
                        "conversation_id": "conv-c8",
                        "client_message_id": "cid-c8",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps(
                            [
                                {"type": "text", "text": "prefix"},
                                {"type": "attachment", "id": "a1"},
                                {"type": "attachment", "id": "a2", "caption": "cap-2"},
                            ]
                        ),
                    },
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="application/octet-stream",
                            content_length=4,
                            filename="f1.bin",
                            payload_bytes=b"1234",
                        ),
                        "files[a2]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f2.png",
                            payload_bytes=b"5678",
                        ),
                    },
                    "message_with_attachments",
                ),
                (
                    # C10 interleaved ordered parts
                    {
                        "conversation_id": "conv-c10",
                        "client_message_id": "cid-c10",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps(
                            [
                                {"type": "text", "text": "first"},
                                {"type": "attachment", "id": "a1", "caption": "cap-1"},
                                {"type": "text", "text": "second"},
                            ]
                        ),
                    },
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="application/pdf",
                            content_length=4,
                            filename="f1.pdf",
                            payload_bytes=b"ijkl",
                        )
                    },
                    "message_with_attachments",
                ),
            ]

            for form_payload, file_payload, expected_mode in scenarios:
                request_obj = SimpleNamespace(
                    form=_AwaitableValue(form_payload),
                    files=_AwaitableValue(file_payload),
                )
                with (
                    patch.object(chat, "request", new=request_obj),
                    patch.object(chat, "jsonify", return_value=fake_response),
                ):
                    response, status = await endpoint(
                        auth_user="user-1",
                        config_provider=lambda: config,
                        logger_provider=lambda: Mock(),
                        web_client_provider=lambda: web_client,
                    )

                self.assertEqual(status, 202)
                self.assertEqual(response.status_code, 200)
                web_client.enqueue_message.assert_awaited()
                kwargs = web_client.enqueue_message.await_args.kwargs
                self.assertEqual(kwargs["message_type"], "composed")
                self.assertEqual(kwargs["metadata"]["composition_mode"], expected_mode)
                self.assertTrue(isinstance(kwargs["metadata"]["parts"], list))
                self.assertTrue(isinstance(kwargs["metadata"]["attachments"], list))
                if "metadata" in form_payload:
                    self.assertEqual(kwargs["metadata"]["metadata"], {"source": "c1"})
                web_client.enqueue_message.reset_mock()

    async def test_messages_create_structured_invalid_matrix_paths(self) -> None:
        endpoint = unwrap(chat.web_messages_create)

        with tempfile.TemporaryDirectory() as tmpdir:
            base_config = _make_config(basedir=tmpdir, max_upload=8, max_attachments=10)

            invalid_cases = [
                # R1 no text and no attachments.
                (
                    {
                        "conversation_id": "conv-r1",
                        "client_message_id": "cid-r1",
                        "composition_mode": "message_with_attachments",
                        "parts": "[]",
                    },
                    {},
                    400,
                ),
                # R2 caption without a valid attachment target.
                (
                    {
                        "conversation_id": "conv-r2",
                        "client_message_id": "cid-r2",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps(
                            [{"type": "text", "text": "t", "caption": "bad"}]
                        ),
                    },
                    {},
                    400,
                ),
                # R3 attachment part missing id/blob linkage.
                (
                    {
                        "conversation_id": "conv-r3",
                        "client_message_id": "cid-r3",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps([{"type": "attachment"}]),
                    },
                    {},
                    400,
                ),
                # attachment_with_caption with no attachment parts.
                (
                    {
                        "conversation_id": "conv-r2-mode-empty",
                        "client_message_id": "cid-r2-mode-empty",
                        "composition_mode": "attachment_with_caption",
                        "parts": json.dumps([{"type": "text", "text": "hello"}]),
                    },
                    {},
                    400,
                ),
                # attachment_with_caption contains text part (invalid caption target).
                (
                    {
                        "conversation_id": "conv-r2-mode-text",
                        "client_message_id": "cid-r2-mode-text",
                        "composition_mode": "attachment_with_caption",
                        "parts": json.dumps(
                            [
                                {"type": "text", "text": "hello"},
                                {"type": "attachment", "id": "a1", "caption": "cap"},
                            ]
                        ),
                    },
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f.png",
                            payload_bytes=b"1234",
                        )
                    },
                    400,
                ),
                # attachment_with_caption requires non-empty caption for each attachment.
                (
                    {
                        "conversation_id": "conv-r2-mode-caption",
                        "client_message_id": "cid-r2-mode-caption",
                        "composition_mode": "attachment_with_caption",
                        "parts": json.dumps([{"type": "attachment", "id": "a1"}]),
                    },
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f.png",
                            payload_bytes=b"1234",
                        )
                    },
                    400,
                ),
                # attachment id exists in parts but upload mapping is missing.
                (
                    {
                        "conversation_id": "conv-r3-missing-upload",
                        "client_message_id": "cid-r3-missing-upload",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps([{"type": "attachment", "id": "a1"}]),
                    },
                    {},
                    400,
                ),
                # R4 unsupported media type.
                (
                    {
                        "conversation_id": "conv-r4",
                        "client_message_id": "cid-r4",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps([{"type": "attachment", "id": "a1"}]),
                    },
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="audio/ogg",
                            content_length=4,
                            filename="f.ogg",
                            payload_bytes=b"1234",
                        )
                    },
                    415,
                ),
                # R6 duplicate attachment ids.
                (
                    {
                        "conversation_id": "conv-r6",
                        "client_message_id": "cid-r6",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps(
                            [
                                {"type": "attachment", "id": "dup"},
                                {"type": "attachment", "id": "dup"},
                            ]
                        ),
                    },
                    {
                        "files[dup]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f.png",
                            payload_bytes=b"1234",
                        )
                    },
                    422,
                ),
                # R6 orphan uploads.
                (
                    {
                        "conversation_id": "conv-r6b",
                        "client_message_id": "cid-r6b",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps([{"type": "attachment", "id": "a1"}]),
                    },
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f1.png",
                            payload_bytes=b"1234",
                        ),
                        "files[a2]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f2.png",
                            payload_bytes=b"5678",
                        ),
                    },
                    422,
                ),
                # Mixed legacy + structured is rejected.
                (
                    {
                        "conversation_id": "conv-mixed",
                        "client_message_id": "cid-mixed",
                        "message_type": "text",
                        "text": "legacy",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps([{"type": "text", "text": "structured"}]),
                    },
                    {},
                    400,
                ),
            ]

            for form_payload, file_payload, expected_code in invalid_cases:
                request_obj = SimpleNamespace(
                    form=_AwaitableValue(form_payload),
                    files=_AwaitableValue(file_payload),
                )
                with (
                    patch.object(chat, "abort", side_effect=_abort_raiser),
                    patch.object(chat, "request", new=request_obj),
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await endpoint(
                            auth_user="user-1",
                            config_provider=lambda: base_config,
                            logger_provider=lambda: Mock(),
                            web_client_provider=lambda: SimpleNamespace(
                                enqueue_message=AsyncMock()
                            ),
                        )
                self.assertEqual(ex.exception.code, expected_code)

            # R5 max attachments / size limits.
            max_count_config = _make_config(basedir=tmpdir, max_upload=8, max_attachments=1)
            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "conv-r5",
                                "client_message_id": "cid-r5",
                                "composition_mode": "message_with_attachments",
                                "parts": json.dumps(
                                    [
                                        {"type": "attachment", "id": "a1"},
                                        {"type": "attachment", "id": "a2"},
                                    ]
                                ),
                            }
                        ),
                        files=_AwaitableValue(
                            {
                                "files[a1]": _DummyUpload(
                                    mimetype="image/png",
                                    content_length=4,
                                    filename="f1.png",
                                    payload_bytes=b"1234",
                                ),
                                "files[a2]": _DummyUpload(
                                    mimetype="image/png",
                                    content_length=4,
                                    filename="f2.png",
                                    payload_bytes=b"5678",
                                ),
                            }
                        ),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="user-1",
                        config_provider=lambda: max_count_config,
                        logger_provider=lambda: Mock(),
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
            self.assertEqual(ex.exception.code, 413)

            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(
                    chat,
                    "request",
                    new=SimpleNamespace(
                        form=_AwaitableValue(
                            {
                                "conversation_id": "conv-r5-size",
                                "client_message_id": "cid-r5-size",
                                "composition_mode": "message_with_attachments",
                                "parts": json.dumps([{"type": "attachment", "id": "a1"}]),
                            }
                        ),
                        files=_AwaitableValue(
                            {
                                "files[a1]": _DummyUpload(
                                    mimetype="image/png",
                                    content_length=9,
                                    filename="f.png",
                                    payload_bytes=b"123456789",
                                )
                            }
                        ),
                    ),
                ),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="user-1",
                        config_provider=lambda: base_config,
                        logger_provider=lambda: Mock(),
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock()
                        ),
                    )
            self.assertEqual(ex.exception.code, 413)

    async def test_messages_create_structured_cleanup_on_enqueue_error(self) -> None:
        endpoint = unwrap(chat.web_messages_create)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(basedir=tmpdir, max_upload=1024, max_attachments=10)
            request_obj = SimpleNamespace(
                form=_AwaitableValue(
                    {
                        "conversation_id": "conv-cleanup",
                        "client_message_id": "cid-cleanup",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps(
                            [
                                {"type": "attachment", "id": "a1"},
                                {"type": "attachment", "id": "a2"},
                            ]
                        ),
                    }
                ),
                files=_AwaitableValue(
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f1.png",
                            payload_bytes=b"1234",
                        ),
                        "files[a2]": _DummyUpload(
                            mimetype="application/pdf",
                            content_length=4,
                            filename="f2.pdf",
                            payload_bytes=b"5678",
                        ),
                    }
                ),
            )

            with (
                patch.object(chat, "abort", side_effect=_abort_raiser),
                patch.object(chat, "request", new=request_obj),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await endpoint(
                        auth_user="user-1",
                        config_provider=lambda: config,
                        logger_provider=lambda: Mock(),
                        web_client_provider=lambda: SimpleNamespace(
                            enqueue_message=AsyncMock(side_effect=OverflowError())
                        ),
                    )
            self.assertEqual(ex.exception.code, 429)
            media_dir = os.path.join(tmpdir, "web_media")
            self.assertTrue(os.path.isdir(media_dir))
            self.assertEqual(os.listdir(media_dir), [])

    async def test_messages_create_structured_enqueue_error_branches(self) -> None:
        endpoint = unwrap(chat.web_messages_create)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _make_config(basedir=tmpdir, max_upload=1024, max_attachments=10)
            base_request = SimpleNamespace(
                form=_AwaitableValue(
                    {
                        "conversation_id": "conv-structured-errors",
                        "client_message_id": "cid-structured-errors",
                        "composition_mode": "message_with_attachments",
                        "parts": json.dumps([{"type": "attachment", "id": "a1"}]),
                    }
                ),
                files=_AwaitableValue(
                    {
                        "files[a1]": _DummyUpload(
                            mimetype="image/png",
                            content_length=4,
                            filename="f.png",
                            payload_bytes=b"1234",
                        )
                    }
                ),
            )

            for expected_code, side_effect in (
                (403, PermissionError()),
                (409, WebConversationTenantConflictError("conversation tenant mismatch")),
                (400, ValueError("bad structured enqueue")),
                (500, RuntimeError("boom")),
            ):
                logger = Mock()
                with (
                    patch.object(chat, "abort", side_effect=_abort_raiser),
                    patch.object(chat, "request", new=base_request),
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await endpoint(
                            auth_user="user-1",
                            config_provider=lambda: config,
                            logger_provider=lambda: logger,
                            web_client_provider=lambda: SimpleNamespace(
                                enqueue_message=AsyncMock(side_effect=side_effect)
                            ),
                        )
                self.assertEqual(ex.exception.code, expected_code)
                if expected_code == 500:
                    logger.error.assert_called_once_with(
                        "Failed to enqueue web message: boom"
                    )

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
