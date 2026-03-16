"""Unit tests for mugen.core.service.messaging.DefaultMessagingService."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import mugen.core.service.messaging as messaging_module
from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import ContextScope
from mugen.core.contract.service.messaging import MessagingTurnRequest
from mugen.core.service.messaging import DefaultMessagingService


class _DummyMhExt:
    def __init__(
        self,
        *,
        platforms: list[str],
        message_types: object,
        response: object = None,
        side_effect: object = None,
    ) -> None:
        self._platforms = set(platforms)
        self.platforms = list(platforms)
        self.message_types = message_types
        self.handle_message = AsyncMock(return_value=response, side_effect=side_effect)

    def platform_supported(self, platform: str) -> bool:
        return platform in self._platforms


class _BuiltinTextHandler:
    def __init__(self, **kwargs) -> None:
        self.init_kwargs = kwargs
        self.handle_message = AsyncMock(
            return_value=[{"type": "text", "content": "builtin-response"}]
        )


def _scope(
    *,
    tenant_id: str = "tenant-1",
    platform: str = "matrix",
    room_id: str = "!room",
    sender_id: str = "@alice",
) -> ContextScope:
    return ContextScope(
        tenant_id=tenant_id,
        platform=platform,
        channel_id=platform,
        room_id=room_id,
        sender_id=sender_id,
        conversation_id=room_id,
    )


class TestMugenServiceMessaging(unittest.IsolatedAsyncioTestCase):
    """Covers messaging runtime orchestration around the context engine seam."""

    def _new_service(
        self,
        *,
        mh_mode: str = "optional",
        environment: str = "test",
    ) -> DefaultMessagingService:
        completion_gateway = Mock()
        completion_gateway.get_completion = AsyncMock()

        logging_gateway = Mock()
        context_engine_service = Mock()
        user_service = Mock()

        svc = DefaultMessagingService(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    environment=environment,
                    messaging=SimpleNamespace(
                        mh_mode=mh_mode,
                        extension_timeout_seconds=10.0,
                    ),
                )
            ),
            completion_gateway=completion_gateway,
            context_engine_service=context_engine_service,
            logging_gateway=logging_gateway,
            user_service=user_service,
        )
        svc._builtin_text_handler = _BuiltinTextHandler()  # pylint: disable=protected-access
        return svc

    def test_init_supports_dict_messaging_config(self) -> None:
        completion_gateway = Mock()
        completion_gateway.get_completion = AsyncMock()

        svc = DefaultMessagingService(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    messaging={
                        "mh_mode": "required",
                        "extension_timeout_seconds": 10.0,
                    }
                )
            ),
            completion_gateway=completion_gateway,
            context_engine_service=Mock(),
            logging_gateway=Mock(),
            user_service=Mock(),
        )

        self.assertEqual(svc._mh_mode, "required")  # pylint: disable=protected-access

    def test_init_rejects_invalid_mh_mode(self) -> None:
        completion_gateway = Mock()
        completion_gateway.get_completion = AsyncMock()

        with self.assertRaisesRegex(ValueError, "mugen.messaging.mh_mode"):
            DefaultMessagingService(
                config=SimpleNamespace(
                    mugen=SimpleNamespace(
                        messaging=SimpleNamespace(
                            mh_mode="invalid",
                            extension_timeout_seconds=10.0,
                        )
                    )
                ),
                completion_gateway=completion_gateway,
                context_engine_service=Mock(),
                logging_gateway=Mock(),
                user_service=Mock(),
            )

    def test_init_wraps_builtin_pipeline_import_error(self) -> None:
        completion_gateway = Mock()
        completion_gateway.get_completion = AsyncMock()

        with patch(
            "mugen.core.service.messaging.importlib.import_module",
            side_effect=ImportError("boom"),
        ):
            with self.assertRaisesRegex(RuntimeError, "built-in text messaging pipeline"):
                DefaultMessagingService(
                    config=SimpleNamespace(
                        mugen=SimpleNamespace(
                            messaging=SimpleNamespace(
                                mh_mode="optional",
                                extension_timeout_seconds=10.0,
                            )
                        )
                    ),
                    completion_gateway=completion_gateway,
                    context_engine_service=Mock(),
                    logging_gateway=Mock(),
                    user_service=Mock(),
                )

    async def test_handle_text_message_uses_builtin_handler_with_fallback_global_scope(
        self,
    ) -> None:
        svc = self._new_service()

        result = await svc.handle_text_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
        )

        self.assertEqual(result, [{"type": "text", "content": "builtin-response"}])
        builtin_call = svc._builtin_text_handler.handle_message.await_args.kwargs  # pylint: disable=protected-access
        builtin_scope = builtin_call["scope"]
        self.assertIsInstance(builtin_scope, ContextScope)
        self.assertEqual(builtin_scope.tenant_id, str(GLOBAL_TENANT_ID))
        self.assertEqual(
            builtin_call["ingress_metadata"]["tenant_resolution"]["mode"],
            "fallback_global",
        )
        self.assertEqual(
            builtin_call["message_context"][-1]["type"],
            "ingress_route",
        )

    async def test_handle_text_message_raises_when_required_mode_has_no_mh_extension(
        self,
    ) -> None:
        svc = self._new_service(mh_mode="required")

        with self.assertRaisesRegex(RuntimeError, "mugen.messaging.mh_mode='required'"):
            await svc.handle_text_message(
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message="hello",
            )

    async def test_handle_text_message_aggregates_matching_handler_responses(self) -> None:
        svc = self._new_service()
        ext_a = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            response=[{"type": "text", "content": "a"}],
        )
        ext_b = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            response=[{"type": "text", "content": "b"}],
        )
        ext_c = _DummyMhExt(
            platforms=["whatsapp"],
            message_types=["text"],
            response=[{"type": "text", "content": "c"}],
        )
        svc._mh_extensions = [ext_a, ext_b, ext_c]  # pylint: disable=protected-access

        scope = _scope()
        result = await svc.handle_text_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
            message_context=[{"type": "seed", "content": "ctx"}],
            scope=scope,
        )

        self.assertEqual(
            result,
            [
                {"type": "text", "content": "a"},
                {"type": "text", "content": "b"},
            ],
        )
        ext_a.handle_message.assert_awaited_once()
        ext_b.handle_message.assert_awaited_once()
        ext_c.handle_message.assert_not_awaited()
        self.assertIs(ext_a.handle_message.await_args.kwargs["scope"], scope)

    async def test_collect_message_handler_responses_rejects_invalid_shapes(self) -> None:
        svc = self._new_service()
        bad_type = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            response="not-a-list",
        )
        bad_item = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            response=[{"type": "text", "content": "ok"}, "bad-item"],
        )
        ignored_type = _DummyMhExt(
            platforms=["matrix"],
            message_types="text",
            response=[{"type": "text", "content": "ignored"}],
        )
        svc._mh_extensions = [bad_type, bad_item, ignored_type]  # pylint: disable=protected-access

        result = await svc._collect_message_handler_responses(  # pylint: disable=protected-access
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
            message_types={"text"},
            scope=_scope(),
        )

        self.assertEqual(result, [{"type": "text", "content": "ok"}])
        svc._logging_gateway.warning.assert_called()  # pylint: disable=protected-access
        ignored_type.handle_message.assert_not_awaited()

    async def test_invoke_message_handler_fail_open_logs_and_returns_none(self) -> None:
        svc = self._new_service()
        ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            side_effect=RuntimeError("boom"),
        )

        result = await svc._invoke_message_handler(  # pylint: disable=protected-access
            extension=ext,
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
            scope=_scope(),
        )

        self.assertIsNone(result)
        self.assertEqual(
            svc._extension_metrics["messaging.extensions.exception"],  # pylint: disable=protected-access
            1,
        )
        svc._logging_gateway.warning.assert_called()  # pylint: disable=protected-access

    async def test_invoke_message_handler_fail_closed_raises_for_critical_extension(
        self,
    ) -> None:
        svc = self._new_service()
        ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            side_effect=asyncio.TimeoutError(),
        )
        svc.bind_mh_extension(ext, critical=True)

        with self.assertRaises(RuntimeError):
            await svc._invoke_message_handler(  # pylint: disable=protected-access
                extension=ext,
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message="hello",
                scope=_scope(),
            )

        self.assertIn(
            ("mh", f"{type(ext).__module__}.{type(ext).__qualname__}", ("matrix",)),
            svc._critical_extension_keys,  # pylint: disable=protected-access
        )

    async def test_handle_media_message_collects_context_then_calls_text_pipeline(self) -> None:
        svc = self._new_service()
        ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["audio"],
            response=[{"type": "audio_summary", "content": {"text": "clip"}}],
        )
        svc._mh_extensions = [ext]  # pylint: disable=protected-access
        svc.handle_text_message = AsyncMock(  # type: ignore[method-assign]
            return_value=[{"type": "text", "content": "ok"}]
        )

        scope = _scope()
        result = await svc.handle_audio_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message={"file_path": "clip.ogg"},
            message_context=[{"type": "seed", "content": "ctx"}],
            scope=scope,
        )

        self.assertEqual(result, [{"type": "text", "content": "ok"}])
        call = svc.handle_text_message.await_args.kwargs
        self.assertEqual(call["message"], "Uploaded an audio file.")
        self.assertEqual(
            call["message_context"][:2],
            [
                {"type": "audio_summary", "content": {"text": "clip"}},
                {"type": "seed", "content": "ctx"},
            ],
        )
        self.assertIs(call["scope"], scope)

    async def test_handle_composed_message_builds_prompt_and_attachment_context(self) -> None:
        svc = self._new_service()
        svc.handle_text_message = AsyncMock(  # type: ignore[method-assign]
            return_value=[{"type": "text", "content": "ok"}]
        )
        media_ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["image"],
            response=[{"type": "image_summary", "content": {"caption": "receipt"}}],
        )
        svc._mh_extensions = [media_ext]  # pylint: disable=protected-access

        scope = _scope()
        message = {
            "parts": [
                {"type": "text", "text": "Please review"},
                {"type": "attachment", "id": "att-1", "caption": "receipt"},
            ],
            "attachments": [
                {
                    "id": "att-1",
                    "file_path": "/tmp/receipt.png",
                    "mime_type": "image/png",
                    "original_filename": "receipt.png",
                    "caption": "receipt",
                    "metadata": {"page": 1},
                }
            ],
            "composition_mode": "message_with_attachments",
            "metadata": {"locale": "en-US"},
        }

        result = await svc.handle_composed_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message=message,
            scope=scope,
        )

        self.assertEqual(result, [{"type": "text", "content": "ok"}])
        text_call = svc.handle_text_message.await_args.kwargs
        self.assertEqual(
            text_call["message"],
            "Please review\n[attachment:att-1] caption=receipt",
        )
        self.assertEqual(
            text_call["attachment_context"],
            [
                {
                    "type": "attachment",
                    "content": {
                        "index": 1,
                        "id": "att-1",
                        "mime_type": "image/png",
                        "filename": "receipt.png",
                        "caption": "receipt",
                        "metadata": {"page": 1},
                        "composition_mode": "message_with_attachments",
                    },
                }
            ],
        )
        self.assertEqual(
            text_call["message_context"][-2:],
            [
                {"type": "image_summary", "content": {"caption": "receipt"}},
                {"type": "composed_metadata", "content": {"metadata": {"locale": "en-US"}}},
            ],
        )

    async def test_handle_message_dispatches_typed_request(self) -> None:
        svc = self._new_service()
        svc.handle_text_message = AsyncMock(  # type: ignore[method-assign]
            return_value=[{"type": "text", "content": "ok"}]
        )

        request = MessagingTurnRequest(
            scope=_scope(),
            message_type="text",
            message="hello",
            message_context=[{"type": "seed", "content": "ctx"}],
            ingress_metadata={"trace": "123"},
        )
        result = await svc.handle_message(request)

        self.assertEqual(result, [{"type": "text", "content": "ok"}])
        text_call = svc.handle_text_message.await_args.kwargs
        self.assertEqual(text_call["platform"], "matrix")
        self.assertEqual(text_call["message_context"], [{"type": "seed", "content": "ctx"}])
        self.assertEqual(text_call["ingress_metadata"], {"trace": "123"})
        self.assertIs(text_call["scope"], request.scope)

    def test_register_methods_update_extension_lists_and_reject_duplicates(self) -> None:
        svc = self._new_service()
        cp = Mock(platforms=["matrix"])
        ct = Mock(platforms=["matrix"])
        mh = _DummyMhExt(platforms=["matrix"], message_types=["text"])
        rpp = Mock(platforms=["matrix"])

        svc.bind_cp_extension(cp)
        svc.bind_ct_extension(ct)
        svc.bind_mh_extension(mh)
        svc.bind_rpp_extension(rpp)

        self.assertEqual(svc.cp_extensions, [cp])
        self.assertEqual(svc.ct_extensions, [ct])
        self.assertEqual(svc.mh_extensions, [mh])
        self.assertEqual(svc.rpp_extensions, [rpp])

        with self.assertRaisesRegex(ValueError, "instance duplicate"):
            svc.bind_mh_extension(mh)

        with self.assertRaisesRegex(ValueError, "logical duplicate"):
            svc.bind_mh_extension(
                _DummyMhExt(platforms=["matrix"], message_types=["text"])
            )

    def test_extension_timeout_resolution_uses_default_in_production(self) -> None:
        completion_gateway = Mock()
        completion_gateway.get_completion = AsyncMock()
        logging_gateway = Mock()

        with patch(
            "mugen.core.service.messaging.importlib.import_module",
            return_value=SimpleNamespace(DefaultTextMHExtension=_BuiltinTextHandler),
        ):
            svc = DefaultMessagingService(
                config=SimpleNamespace(
                    mugen=SimpleNamespace(
                        environment="production",
                        messaging=SimpleNamespace(
                            mh_mode="optional",
                            extension_timeout_seconds=None,
                        ),
                    )
                ),
                completion_gateway=completion_gateway,
                context_engine_service=Mock(),
                logging_gateway=logging_gateway,
                user_service=Mock(),
            )

        self.assertEqual(
            svc._extension_timeout_seconds,  # pylint: disable=protected-access
            svc._default_extension_timeout_seconds,  # pylint: disable=protected-access
        )
        logging_gateway.warning.assert_called_once()

    def test_extension_timeout_resolution_non_production_and_parser_branch(self) -> None:
        svc = self._new_service(environment="test")
        self.assertEqual(
            svc._resolve_extension_timeout_seconds(),  # pylint: disable=protected-access
            10.0,
        )

        svc._config = SimpleNamespace(  # pylint: disable=protected-access
            mugen=SimpleNamespace(
                environment="test",
                messaging=SimpleNamespace(
                    mh_mode="optional",
                    extension_timeout_seconds=None,
                ),
            )
        )
        self.assertIsNone(
            svc._resolve_extension_timeout_seconds()  # pylint: disable=protected-access
        )

        svc._config = SimpleNamespace(  # pylint: disable=protected-access
            mugen=SimpleNamespace(
                environment="test",
                messaging=SimpleNamespace(
                    mh_mode="optional",
                    extension_timeout_seconds="5.5",
                ),
            )
        )
        with patch.object(
            messaging_module,
            "parse_optional_positive_finite_float",
            return_value=5.5,
        ) as parse_optional_positive_finite_float:
            self.assertEqual(
                svc._resolve_extension_timeout_seconds(),  # pylint: disable=protected-access
                5.5,
            )
        parse_optional_positive_finite_float.assert_called_once_with(
            "5.5",
            "mugen.messaging.extension_timeout_seconds",
        )

    def test_extension_platform_key_and_fail_closed_without_cause(self) -> None:
        svc = self._new_service()
        ext = _DummyMhExt(platforms=["matrix"], message_types=["text"])
        ext.platforms = "matrix"

        self.assertEqual(
            svc._extension_platform_key(ext),  # pylint: disable=protected-access
            (),
        )

        svc.bind_mh_extension(_DummyMhExt(platforms=["matrix"], message_types=["text"]), critical=True)
        critical_ext = svc.mh_extensions[0]
        extension_name = f"{type(critical_ext).__module__}.{type(critical_ext).__qualname__}"
        with self.assertRaisesRegex(RuntimeError, "critical failure"):
            svc._handle_extension_handler_failure(  # pylint: disable=protected-access
                extension_name=extension_name,
                extension=critical_ext,
                kind="mh",
                message="critical failure",
                cause=None,
            )

    async def test_invoke_message_handler_without_timeout_covers_success_and_exception_paths(
        self,
    ) -> None:
        svc = self._new_service()
        svc._extension_timeout_seconds = None  # pylint: disable=protected-access
        success_ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            response=[{"type": "text", "content": "ok"}],
        )
        failing_ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            side_effect=RuntimeError("boom"),
        )

        success = await svc._invoke_message_handler(  # pylint: disable=protected-access
            extension=success_ext,
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
            scope=_scope(),
        )
        failure = await svc._invoke_message_handler(  # pylint: disable=protected-access
            extension=failing_ext,
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
            scope=_scope(),
        )

        self.assertEqual(success, [{"type": "text", "content": "ok"}])
        self.assertIsNone(failure)

        cancelled_ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            side_effect=asyncio.CancelledError(),
        )
        with self.assertRaises(asyncio.CancelledError):
            await svc._invoke_message_handler(  # pylint: disable=protected-access
                extension=cancelled_ext,
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message="hello",
                scope=_scope(),
            )

    async def test_invoke_message_handler_timeout_and_cancelled_paths(self) -> None:
        svc = self._new_service()
        timeout_ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            side_effect=asyncio.TimeoutError(),
        )
        cancelled_ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            side_effect=asyncio.CancelledError(),
        )

        self.assertIsNone(
            await svc._invoke_message_handler(  # pylint: disable=protected-access
                extension=timeout_ext,
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message="hello",
                scope=_scope(),
            )
        )
        with self.assertRaises(asyncio.CancelledError):
            await svc._invoke_message_handler(  # pylint: disable=protected-access
                extension=cancelled_ext,
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message="hello",
                scope=_scope(),
            )

    async def test_handle_file_image_and_video_messages_return_unsupported_fallbacks(
        self,
    ) -> None:
        svc = self._new_service()

        self.assertEqual(
            await svc.handle_audio_message(
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message={"file_path": "a.ogg"},
            ),
            [{"type": "text", "content": "Unsupported message type: audio."}],
        )

        self.assertEqual(
            await svc.handle_file_message(
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message={"file_path": "a.pdf"},
            ),
            [{"type": "text", "content": "Unsupported message type: file."}],
        )
        self.assertEqual(
            await svc.handle_image_message(
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message={"file_path": "a.png"},
            ),
            [{"type": "text", "content": "Unsupported message type: image."}],
        )
        self.assertEqual(
            await svc.handle_video_message(
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message={"file_path": "a.mp4"},
            ),
            [{"type": "text", "content": "Unsupported message type: video."}],
        )

    async def test_handle_message_dispatches_all_non_text_types_and_rejects_invalid_payloads(
        self,
    ) -> None:
        svc = self._new_service()
        svc.handle_composed_message = AsyncMock(return_value=[])  # type: ignore[method-assign]
        svc.handle_audio_message = AsyncMock(return_value=[])  # type: ignore[method-assign]
        svc.handle_file_message = AsyncMock(return_value=[])  # type: ignore[method-assign]
        svc.handle_image_message = AsyncMock(return_value=[])  # type: ignore[method-assign]
        svc.handle_video_message = AsyncMock(return_value=[])  # type: ignore[method-assign]
        scope = _scope()

        for message_type, handler in (
            ("composed", svc.handle_composed_message),
            ("audio", svc.handle_audio_message),
            ("file", svc.handle_file_message),
            ("image", svc.handle_image_message),
            ("video", svc.handle_video_message),
        ):
            await svc.handle_message(
                MessagingTurnRequest(
                    scope=scope,
                    message_type=message_type,
                    message={},
                )
            )
            handler.assert_awaited_once()
            handler.reset_mock()

        with self.assertRaisesRegex(ValueError, "Composed messaging turns require object payloads"):
            await svc.handle_message(
                MessagingTurnRequest(scope=scope, message_type="composed", message="bad")
            )
        with self.assertRaisesRegex(ValueError, "Audio messaging turns require object payloads"):
            await svc.handle_message(
                MessagingTurnRequest(scope=scope, message_type="audio", message="bad")
            )
        with self.assertRaisesRegex(ValueError, "File messaging turns require object payloads"):
            await svc.handle_message(
                MessagingTurnRequest(scope=scope, message_type="file", message="bad")
            )
        with self.assertRaisesRegex(ValueError, "Image messaging turns require object payloads"):
            await svc.handle_message(
                MessagingTurnRequest(scope=scope, message_type="image", message="bad")
            )
        with self.assertRaisesRegex(ValueError, "Video messaging turns require object payloads"):
            await svc.handle_message(
                MessagingTurnRequest(scope=scope, message_type="video", message="bad")
            )
        with self.assertRaisesRegex(ValueError, "Unsupported message type: unknown"):
            await svc.handle_message(
                MessagingTurnRequest(scope=scope, message_type="unknown", message="hello")
            )

    async def test_collect_composed_media_context_covers_type_inference_and_empty_responses(
        self,
    ) -> None:
        svc = self._new_service()
        ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["audio", "video", "image", "file"],
            response=[{"type": "summary", "content": {"ok": True}}],
        )
        svc._mh_extensions = [ext]  # pylint: disable=protected-access

        media_context = await svc._collect_composed_media_context(  # pylint: disable=protected-access
            platform="matrix",
            room_id="!room",
            sender="@alice",
            attachments=[
                {"id": "a1", "mime_type": "audio/ogg"},
                {"id": "a2", "mime_type": "video/mp4"},
                {"id": "a3", "mime_type": "image/png"},
                {"id": "a4", "mime_type": "application/pdf"},
            ],
            composition_mode="message_with_attachments",
            client_message_id="client-1",
            ingress_metadata={},
            message_id="msg-1",
            trace_id="trace-1",
            scope=_scope(),
        )

        self.assertEqual(len(media_context), 4)
        self.assertEqual(
            [
                svc._infer_media_message_type("audio/ogg"),  # pylint: disable=protected-access
                svc._infer_media_message_type("video/mp4"),  # pylint: disable=protected-access
                svc._infer_media_message_type("image/png"),  # pylint: disable=protected-access
                svc._infer_media_message_type("application/pdf"),  # pylint: disable=protected-access
            ],
            ["audio", "video", "image", "file"],
        )

        svc._invoke_message_handler = AsyncMock(return_value=None)  # type: ignore[method-assign]
        self.assertEqual(
            await svc._collect_composed_media_context(  # pylint: disable=protected-access
                platform="matrix",
                room_id="!room",
                sender="@alice",
                attachments=[{"id": "a1", "mime_type": "image/png"}],
                composition_mode="message_with_attachments",
                client_message_id=None,
                ingress_metadata={},
                message_id=None,
                trace_id=None,
                scope=_scope(),
            ),
            [],
        )

    async def test_media_handlers_cover_success_paths_for_file_image_and_video(self) -> None:
        svc = self._new_service()
        for message_type, method, expected_prompt in (
            ("file", svc.handle_file_message, "Uploaded a file."),
            ("image", svc.handle_image_message, "Uploaded an image file."),
            ("video", svc.handle_video_message, "Uploaded video file."),
        ):
            ext = _DummyMhExt(
                platforms=["matrix"],
                message_types=[message_type],
                response=[{"type": f"{message_type}_summary", "content": {"ok": True}}],
            )
            svc._mh_extensions = [ext]  # pylint: disable=protected-access
            svc.handle_text_message = AsyncMock(  # type: ignore[method-assign]
                return_value=[{"type": "text", "content": "ok"}]
            )

            result = await method(
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message={"file_path": f"a.{message_type}"},
                scope=_scope(),
            )

            self.assertEqual(result, [{"type": "text", "content": "ok"}])
            self.assertEqual(
                svc.handle_text_message.await_args.kwargs["message"],
                expected_prompt,
            )

    def test_metadata_route_and_composed_helper_methods_cover_edge_cases(self) -> None:
        svc = self._new_service()
        global_scope = _scope(tenant_id=str(GLOBAL_TENANT_ID))
        existing_context = [{"type": "ingress_route", "content": {"tenant_id": "tenant-1"}}]

        self.assertEqual(
            svc._message_payload_metadata("hello"),  # pylint: disable=protected-access
            {},
        )
        self.assertEqual(
            svc._message_payload_metadata({"metadata": "bad"}),  # pylint: disable=protected-access
            {},
        )
        self.assertEqual(
            svc._merge_ingress_metadata(  # pylint: disable=protected-access
                message={"metadata": {"a": 1}},
                ingress_metadata={"b": 2},
            ),
            {"a": 1, "b": 2},
        )
        self.assertIsNone(svc._metadata_text(1))  # pylint: disable=protected-access
        self.assertIsNone(svc._metadata_text("   "))  # pylint: disable=protected-access
        self.assertEqual(
            svc._metadata_text(" hi "),  # pylint: disable=protected-access
            "hi",
        )
        self.assertEqual(
            svc._extract_ingress_route(  # pylint: disable=protected-access
                message={"metadata": {"ingress_route": {"tenant_id": "message"}}},
                message_context=[{"type": "ingress_route", "content": {"tenant_id": "ctx"}}],
                ingress_metadata={"ingress_route": {"tenant_id": "meta"}},
            ),
            {"tenant_id": "meta"},
        )
        self.assertEqual(
            svc._extract_ingress_route(  # pylint: disable=protected-access
                message={"metadata": {"ingress_route": {"tenant_id": "message"}}},
                message_context=[{"type": "ingress_route", "content": {"tenant_id": "ctx"}}],
                ingress_metadata={},
            ),
            {"tenant_id": "message"},
        )
        self.assertEqual(
            svc._extract_ingress_route(  # pylint: disable=protected-access
                message="hello",
                message_context=[{"type": "ingress_route", "content": {"tenant_id": "ctx"}}],
                ingress_metadata={},
            ),
            {"tenant_id": "ctx"},
        )
        self.assertEqual(
            svc._extract_ingress_route(  # pylint: disable=protected-access
                message="hello",
                message_context=[
                    {"type": "ingress_route", "content": "bad"},
                    {"type": "ingress_route", "content": {"tenant_id": "ctx"}},
                ],
                ingress_metadata={},
            ),
            {"tenant_id": "ctx"},
        )
        self.assertIs(
            svc._ensure_ingress_route_message_context(existing_context, {"tenant_id": "tenant-1"}),  # pylint: disable=protected-access
            existing_context,
        )
        self.assertEqual(
            svc._route_from_scope(  # pylint: disable=protected-access
                scope=global_scope,
                platform="matrix",
                ingress_route=None,
            )["tenant_slug"],
            "global",
        )
        with self.assertRaisesRegex(RuntimeError, "does not match ContextScope"):
            svc._route_from_scope(  # pylint: disable=protected-access
                scope=_scope(),
                platform="matrix",
                ingress_route={"tenant_id": "other"},
            )
        self.assertEqual(
            svc._route_from_scope(  # pylint: disable=protected-access
                scope=_scope(),
                platform="matrix",
                ingress_route={"tenant_id": "tenant-1"},
            ),
            {
                "tenant_id": "tenant-1",
                "platform": "matrix",
                "channel_key": "matrix",
                "identifier_claims": {},
            },
        )
        self.assertEqual(
            svc._build_composed_text_prompt(  # pylint: disable=protected-access
                parts=[
                    {"type": "text", "text": "hello"},
                    {"type": "attachment", "id": "a1", "caption": "receipt"},
                    {"type": "unknown", "text": "skip"},
                ]
            ),
            "hello\n[attachment:a1] caption=receipt",
        )
        self.assertEqual(
            svc._build_composed_text_prompt(parts=[]),  # pylint: disable=protected-access
            "",
        )
        self.assertEqual(
            svc._build_composed_text_prompt(  # pylint: disable=protected-access
                parts=[{"type": "attachment", "id": "a2", "caption": ""}]
            ),
            "[attachment:a2]",
        )
        self.assertIsNone(
            svc._build_composed_attachment_context(  # pylint: disable=protected-access
                attachments=[],
                composition_mode="message_with_attachments",
            )
        )

    def test_resolve_turn_scope_covers_explicit_scope_synthesis_and_route_mismatch(self) -> None:
        svc = self._new_service()
        scope = _scope()

        resolved_scope, message_context, attachment_context, ingress_metadata = (
            svc._resolve_turn_scope(  # pylint: disable=protected-access
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message="hello",
                message_context=["bad", {"type": "seed", "content": "ctx"}],
                attachment_context="bad",
                ingress_metadata=None,
                scope=scope,
            )
        )
        self.assertIs(resolved_scope, scope)
        self.assertEqual(
            message_context,
            [
                {"type": "seed", "content": "ctx"},
                {
                    "type": "ingress_route",
                    "content": ingress_metadata["ingress_route"],
                },
            ],
        )
        self.assertEqual(attachment_context, [])
        self.assertEqual(ingress_metadata["tenant_resolution"]["mode"], "resolved")

        routed_scope = _scope()
        _, routed_context, _, routed_metadata = svc._resolve_turn_scope(  # pylint: disable=protected-access
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
            message_context=None,
            attachment_context=None,
            ingress_metadata={
                "ingress_route": {
                    "tenant_id": routed_scope.tenant_id,
                    "tenant_resolution": {"mode": "resolved", "source": "seed"},
                }
            },
            scope=routed_scope,
        )
        self.assertEqual(routed_metadata["tenant_resolution"]["source"], "seed")
        self.assertEqual(routed_context[-1]["type"], "ingress_route")

        global_scope = _scope(tenant_id=str(GLOBAL_TENANT_ID))
        _, _, _, global_metadata = svc._resolve_turn_scope(  # pylint: disable=protected-access
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
            message_context=None,
            attachment_context=None,
            ingress_metadata=None,
            scope=global_scope,
        )
        self.assertEqual(global_metadata["tenant_resolution"]["mode"], "fallback_global")

        with self.assertRaisesRegex(RuntimeError, "does not match ContextScope"):
            svc._resolve_turn_scope(  # pylint: disable=protected-access
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message="hello",
                message_context=None,
                attachment_context=None,
                ingress_metadata={"ingress_route": {"tenant_id": "other"}},
                scope=scope,
            )

    async def test_handle_composed_message_without_dict_metadata_skips_composed_metadata(
        self,
    ) -> None:
        svc = self._new_service()
        svc.handle_text_message = AsyncMock(  # type: ignore[method-assign]
            return_value=[{"type": "text", "content": "ok"}]
        )

        result = await svc.handle_composed_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message={
                "parts": [{"type": "text", "text": "hi"}],
                "attachments": [],
                "composition_mode": "message_with_attachments",
            },
            scope=_scope(),
        )

        self.assertEqual(result, [{"type": "text", "content": "ok"}])
        self.assertEqual(
            svc.handle_text_message.await_args.kwargs["message_context"][-1]["type"],
            "ingress_route",
        )

    async def test_collect_message_handler_responses_skips_non_matching_message_type_lists(
        self,
    ) -> None:
        svc = self._new_service()
        skipped = _DummyMhExt(
            platforms=["matrix"],
            message_types=["image"],
            response=[{"type": "text", "content": "skip"}],
        )
        svc._mh_extensions = [skipped]  # pylint: disable=protected-access

        self.assertEqual(
            await svc._collect_message_handler_responses(  # pylint: disable=protected-access
                platform="matrix",
                room_id="!room",
                sender="@alice",
                message="hello",
                message_types={"text"},
                scope=_scope(),
            ),
            [],
        )
        skipped.handle_message.assert_not_awaited()

    async def test_handle_message_rejects_non_string_text_payload(self) -> None:
        svc = self._new_service()

        with self.assertRaisesRegex(ValueError, "Text messaging turns require str payloads"):
            await svc.handle_message(
                MessagingTurnRequest(
                    scope=_scope(),
                    message_type="text",
                    message={"body": "bad"},
                )
            )
