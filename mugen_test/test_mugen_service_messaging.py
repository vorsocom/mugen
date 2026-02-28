"""Unit tests for mugen.core.service.messaging.DefaultMessagingService."""

import asyncio
from types import SimpleNamespace
import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock

from mugen.core.service.messaging import DefaultMessagingService


class _DummyMhExt:
    def __init__(
        self,
        *,
        platforms: list[str],
        message_types: list[str] | Any,
        response: Any = None,
        callback: Any = None,
    ) -> None:
        self._platforms = set(platforms)
        self.message_types = message_types
        self._response = response
        self._callback = callback
        self.handle_message = AsyncMock(side_effect=self._handle)

    def platform_supported(self, platform: str) -> bool:
        return platform in self._platforms

    async def _handle(self, **kwargs):
        if self._callback is None:
            return self._response

        result = self._callback(**kwargs)
        if asyncio.iscoroutine(result):
            return await result

        return result


class TestMugenServiceMessaging(unittest.IsolatedAsyncioTestCase):
    """Tests message handler fanout and extension registration."""

    def _new_service(self) -> DefaultMessagingService:
        svc = DefaultMessagingService(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    messaging=SimpleNamespace(extension_timeout_seconds=10.0)
                )
            ),
            completion_gateway=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            user_service=Mock(),
        )
        svc._cp_extensions = []
        svc._ct_extensions = []
        svc._ctx_extensions = []
        svc._mh_extensions = []
        svc._rag_extensions = []
        svc._rpp_extensions = []
        return svc

    async def test_handle_text_message_returns_unsupported_when_no_match(self) -> None:
        svc = self._new_service()
        svc._mh_extensions = [
            _DummyMhExt(
                platforms=["matrix"],
                message_types=["audio"],
                response=[{"type": "text", "content": "ignored"}],
            ),
        ]

        result = await svc.handle_text_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
        )

        self.assertEqual(
            result,
            [{"type": "text", "content": "Unsupported message type: text."}],
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
        svc._mh_extensions = [ext_a, ext_b, ext_c]

        result = await svc.handle_text_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
            message_context=[{"type": "ctx", "content": "ctx"}],
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

    async def test_handle_audio_file_image_video_call_text_pipeline(self) -> None:
        svc = self._new_service()
        ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["audio", "file", "image", "video"],
            response=[{"type": "ctx", "content": "x"}],
        )
        svc._mh_extensions = [ext]
        svc.handle_text_message = AsyncMock(
            return_value=[{"type": "text", "content": "ok"}]
        )

        await svc.handle_audio_message("matrix", "!room", "@alice", {"k": 1})
        await svc.handle_file_message("matrix", "!room", "@alice", {"k": 2})
        await svc.handle_image_message("matrix", "!room", "@alice", {"k": 3})
        await svc.handle_video_message("matrix", "!room", "@alice", {"k": 4})

        self.assertEqual(svc.handle_text_message.await_count, 4)
        audio_call = svc.handle_text_message.await_args_list[0].kwargs
        file_call = svc.handle_text_message.await_args_list[1].kwargs
        image_call = svc.handle_text_message.await_args_list[2].kwargs
        video_call = svc.handle_text_message.await_args_list[3].kwargs
        self.assertEqual(audio_call["message"], "Uploaded an audio file.")
        self.assertEqual(file_call["message"], "Uploaded a file.")
        self.assertEqual(image_call["message"], "Uploaded an image file.")
        self.assertEqual(video_call["message"], "Uploaded video file.")

    async def test_handlers_skip_unsupported_platform_and_ignore_empty_responses(
        self,
    ) -> None:
        svc = self._new_service()
        unsupported = _DummyMhExt(
            platforms=["whatsapp"],
            message_types=["audio", "file", "image", "text", "video"],
            response=[{"type": "ctx", "content": "unsupported"}],
        )
        empty = _DummyMhExt(
            platforms=["matrix"],
            message_types=["audio", "file", "image", "text", "video"],
            response=[],
        )
        useful = _DummyMhExt(
            platforms=["matrix"],
            message_types=["audio", "file", "image", "text", "video"],
            response=[{"type": "ctx", "content": "ok"}],
        )
        svc._mh_extensions = [unsupported, empty, useful]

        audio = await svc.handle_audio_message("matrix", "!room", "@alice", {})
        file_resp = await svc.handle_file_message("matrix", "!room", "@alice", {})
        image = await svc.handle_image_message("matrix", "!room", "@alice", {})
        text = await svc.handle_text_message("matrix", "!room", "@alice", "hello")
        video = await svc.handle_video_message("matrix", "!room", "@alice", {})

        self.assertEqual(audio, [{"type": "ctx", "content": "ok"}])
        self.assertEqual(file_resp, [{"type": "ctx", "content": "ok"}])
        self.assertEqual(image, [{"type": "ctx", "content": "ok"}])
        self.assertEqual(text, [{"type": "ctx", "content": "ok"}])
        self.assertEqual(video, [{"type": "ctx", "content": "ok"}])
        unsupported.handle_message.assert_not_awaited()

    async def test_handle_audio_file_image_video_return_unsupported_when_no_match(
        self,
    ) -> None:
        svc = self._new_service()
        svc._mh_extensions = [
            _DummyMhExt(
                platforms=["matrix"],
                message_types=["text"],
                response=[{"type": "ctx", "content": "x"}],
            ),
        ]

        audio = await svc.handle_audio_message("matrix", "!room", "@alice", {})
        file_resp = await svc.handle_file_message("matrix", "!room", "@alice", {})
        image = await svc.handle_image_message("matrix", "!room", "@alice", {})
        video = await svc.handle_video_message("matrix", "!room", "@alice", {})

        self.assertEqual(
            audio,
            [{"type": "text", "content": "Unsupported message type: audio."}],
        )
        self.assertEqual(
            file_resp,
            [{"type": "text", "content": "Unsupported message type: file."}],
        )
        self.assertEqual(
            image,
            [{"type": "text", "content": "Unsupported message type: image."}],
        )
        self.assertEqual(
            video,
            [{"type": "text", "content": "Unsupported message type: video."}],
        )

    async def test_handle_composed_message_routes_media_context_and_synthesizes_once(
        self,
    ) -> None:
        svc = self._new_service()
        text_ext = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response=[{"type": "text", "content": "final"}],
        )

        async def _media_callback(**kwargs):
            message = kwargs["message"]
            return [
                {
                    "type": "ctx",
                    "content": {
                        "attachment_id": message.get("attachment_id"),
                        "mime_type": message.get("mime_type"),
                    },
                }
            ]

        media_ext = _DummyMhExt(
            platforms=["web"],
            message_types=["audio", "file", "image", "video"],
            callback=_media_callback,
        )
        svc._mh_extensions = [text_ext, media_ext]

        result = await svc.handle_composed_message(
            platform="web",
            room_id="conv-1",
            sender="user-1",
            message={
                "composition_mode": "message_with_attachments",
                "parts": [
                    {"type": "text", "text": "first"},
                    {"type": "attachment", "id": "a1", "caption": "cap-1"},
                    {"type": "attachment", "id": "a2"},
                    {"type": "text", "text": "last"},
                ],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1.ogg",
                        "mime_type": "audio/ogg",
                        "original_filename": "a1.ogg",
                        "metadata": {"k": "v"},
                        "caption": "cap-1",
                    },
                    {
                        "id": "a2",
                        "file_path": "/tmp/a2.pdf",
                        "mime_type": "application/pdf",
                        "original_filename": "a2.pdf",
                        "metadata": {},
                        "caption": None,
                    },
                ],
                "metadata": {"source": "web"},
                "client_message_id": "cid-1",
            },
        )

        self.assertEqual(result, [{"type": "text", "content": "final"}])
        self.assertEqual(media_ext.handle_message.await_count, 2)
        text_ext.handle_message.assert_awaited_once()
        text_call = text_ext.handle_message.await_args.kwargs
        self.assertEqual(
            text_call["message"],
            "first\n[attachment:a1] caption=cap-1\n[attachment:a2]\nlast",
        )
        self.assertEqual(text_call["message_context"][0]["content"]["id"], "a1")
        self.assertEqual(text_call["message_context"][1]["content"]["id"], "a2")
        self.assertEqual(
            text_call["message_context"][2]["content"]["attachment_id"],
            "a1",
        )
        self.assertEqual(
            text_call["message_context"][3]["content"]["attachment_id"],
            "a2",
        )
        self.assertEqual(text_call["message_context"][4]["type"], "composed_metadata")

    async def test_handle_composed_message_still_synthesizes_without_media_handlers(self) -> None:
        svc = self._new_service()
        text_ext = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response=[{"type": "text", "content": "only-text-synth"}],
        )
        svc._mh_extensions = [text_ext]

        result = await svc.handle_composed_message(
            platform="web",
            room_id="conv-2",
            sender="user-1",
            message={
                "composition_mode": "attachment_with_caption",
                "parts": [{"type": "attachment", "id": "a1", "caption": "caption-1"}],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1.jpg",
                        "mime_type": "image/jpeg",
                        "original_filename": "a1.jpg",
                        "metadata": {},
                        "caption": "caption-1",
                    }
                ],
            },
        )

        self.assertEqual(result, [{"type": "text", "content": "only-text-synth"}])
        text_ext.handle_message.assert_awaited_once()
        text_call = text_ext.handle_message.await_args.kwargs
        self.assertEqual(text_call["message"], "[attachment:a1] caption=caption-1")
        self.assertEqual(text_call["message_context"][0]["type"], "attachment")

    async def test_handle_composed_message_text_only_path_uses_no_attachment_context(
        self,
    ) -> None:
        svc = self._new_service()
        text_ext = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response=[{"type": "text", "content": "text-only"}],
        )
        svc._mh_extensions = [text_ext]

        result = await svc.handle_composed_message(
            platform="web",
            room_id="conv-4",
            sender="user-1",
            message={
                "composition_mode": "message_with_attachments",
                "parts": [{"type": "text", "text": "hello"}],
                "attachments": [],
            },
        )
        self.assertEqual(result, [{"type": "text", "content": "text-only"}])
        text_ext.handle_message.assert_awaited_once()
        text_call = text_ext.handle_message.await_args.kwargs
        self.assertIsNone(text_call["message_context"])

    async def test_collect_message_handler_responses_ignores_non_list_message_types(
        self,
    ) -> None:
        svc = self._new_service()
        invalid_ext = _DummyMhExt(
            platforms=["web"],
            message_types="text",
            response=[{"type": "ctx", "content": "invalid"}],
        )
        valid_ext = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response=[{"type": "ctx", "content": "valid"}],
        )
        svc._mh_extensions = [invalid_ext, valid_ext]

        responses = await svc._collect_message_handler_responses(  # pylint: disable=protected-access
            platform="web",
            room_id="conv-3",
            sender="user-1",
            message="hello",
            message_types={"text"},
        )
        self.assertEqual(responses, [{"type": "ctx", "content": "valid"}])
        invalid_ext.handle_message.assert_not_awaited()
        valid_ext.handle_message.assert_awaited_once()

    async def test_collect_message_handler_responses_rejects_non_list_handler_response(
        self,
    ) -> None:
        svc = self._new_service()
        invalid_response = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response={"type": "ctx", "content": "bad-shape"},
        )
        valid_response = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response=[{"type": "ctx", "content": "ok"}],
        )
        svc._mh_extensions = [invalid_response, valid_response]

        responses = await svc._collect_message_handler_responses(  # pylint: disable=protected-access
            platform="web",
            room_id="conv-shape",
            sender="user-shape",
            message="hello",
            message_types={"text"},
        )
        self.assertEqual(responses, [{"type": "ctx", "content": "ok"}])
        self.assertTrue(
            any(
                "invalid response type" in str(call.args[0]).lower()
                and "dict" in str(call.args[0]).lower()
                for call in svc._logging_gateway.warning.call_args_list  # pylint: disable=protected-access
            )
        )

    async def test_collect_message_handler_responses_drops_non_dict_list_items(self) -> None:
        svc = self._new_service()
        mixed_response = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response=[
                {"type": "ctx", "content": "first"},
                "bad-item",
                99,
                {"type": "ctx", "content": "second"},
            ],
        )
        svc._mh_extensions = [mixed_response]

        responses = await svc._collect_message_handler_responses(  # pylint: disable=protected-access
            platform="web",
            room_id="conv-items",
            sender="user-items",
            message="hello",
            message_types={"text"},
        )
        self.assertEqual(
            responses,
            [
                {"type": "ctx", "content": "first"},
                {"type": "ctx", "content": "second"},
            ],
        )
        self.assertTrue(
            any(
                "invalid response item" in str(call.args[0]).lower()
                and "str" in str(call.args[0]).lower()
                for call in svc._logging_gateway.warning.call_args_list  # pylint: disable=protected-access
            )
        )

    async def test_handle_text_message_times_out_hung_extension_and_continues(
        self,
    ) -> None:
        svc = self._new_service()
        svc._extension_timeout_seconds = 0.01  # pylint: disable=protected-access

        async def _hung_callback(**_kwargs):
            await asyncio.sleep(10)
            return [{"type": "text", "content": "late"}]

        hung = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            callback=_hung_callback,
        )
        fast = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response=[{"type": "text", "content": "fast"}],
        )
        svc._mh_extensions = [hung, fast]

        responses = await svc.handle_text_message(
            platform="web",
            room_id="conv-timeout",
            sender="user-timeout",
            message="hello",
        )

        self.assertEqual(responses, [{"type": "text", "content": "fast"}])
        self.assertTrue(svc._logging_gateway.warning.called)  # pylint: disable=protected-access
        self.assertTrue(
            any(
                "timed out" in str(call.args[0])
                for call in svc._logging_gateway.warning.call_args_list  # pylint: disable=protected-access
            )
        )

    async def test_handle_text_message_logs_and_continues_when_handler_raises(self) -> None:
        svc = self._new_service()

        async def _raise(**_kwargs):
            raise RuntimeError("extension blew up")

        broken = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            callback=_raise,
        )
        healthy = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            response=[{"type": "text", "content": "ok"}],
        )
        svc._mh_extensions = [broken, healthy]

        responses = await svc.handle_text_message(
            platform="web",
            room_id="conv-err",
            sender="user-err",
            message="hello",
        )

        self.assertEqual(responses, [{"type": "text", "content": "ok"}])
        self.assertTrue(
            any(
                "handler failed" in str(call.args[0]).lower()
                and "RuntimeError" in str(call.args[0])
                for call in svc._logging_gateway.warning.call_args_list  # pylint: disable=protected-access
            )
        )

    async def test_handle_text_message_without_timeout_logs_and_continues_on_handler_error(
        self,
    ) -> None:
        svc = self._new_service()
        svc._extension_timeout_seconds = None  # pylint: disable=protected-access

        async def _raise(**_kwargs):
            raise RuntimeError("extension blew up")

        broken = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            callback=_raise,
        )
        healthy = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            response=[{"type": "text", "content": "ok"}],
        )
        svc._mh_extensions = [broken, healthy]

        responses = await svc.handle_text_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
        )

        self.assertEqual(responses, [{"type": "text", "content": "ok"}])
        self.assertTrue(
            any(
                "handler failed" in str(call.args[0]).lower()
                and "RuntimeError" in str(call.args[0])
                for call in svc._logging_gateway.warning.call_args_list  # pylint: disable=protected-access
            )
        )

    async def test_invoke_message_handler_propagates_cancellation_without_timeout(self) -> None:
        svc = self._new_service()
        svc._extension_timeout_seconds = None  # pylint: disable=protected-access

        async def _cancel(**_kwargs):
            raise asyncio.CancelledError()

        ext = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            callback=_cancel,
        )

        with self.assertRaises(asyncio.CancelledError):
            await svc._invoke_message_handler(  # pylint: disable=protected-access
                extension=ext,
                platform="web",
                room_id="conv-cancel",
                sender="user-cancel",
                message="hello",
            )

    async def test_invoke_message_handler_propagates_cancellation_with_timeout(self) -> None:
        svc = self._new_service()
        svc._extension_timeout_seconds = 10.0  # pylint: disable=protected-access

        async def _cancel(**_kwargs):
            raise asyncio.CancelledError()

        ext = _DummyMhExt(
            platforms=["web"],
            message_types=["text"],
            callback=_cancel,
        )

        with self.assertRaises(asyncio.CancelledError):
            await svc._invoke_message_handler(  # pylint: disable=protected-access
                extension=ext,
                platform="web",
                room_id="conv-cancel",
                sender="user-cancel",
                message="hello",
            )

    async def test_handle_text_message_without_timeout_awaits_handler_directly(self) -> None:
        svc = self._new_service()
        svc._extension_timeout_seconds = None  # pylint: disable=protected-access
        ext = _DummyMhExt(
            platforms=["matrix"],
            message_types=["text"],
            response=[{"type": "text", "content": "ok"}],
        )
        svc._mh_extensions = [ext]

        result = await svc.handle_text_message(
            platform="matrix",
            room_id="!room",
            sender="@alice",
            message="hello",
        )
        self.assertEqual(result, [{"type": "text", "content": "ok"}])

    def test_extension_timeout_resolution_handles_invalid_shapes(self) -> None:
        svc = self._new_service()

        svc._config = SimpleNamespace(  # pylint: disable=protected-access
            mugen=SimpleNamespace(messaging=SimpleNamespace(extension_timeout_seconds=None))
        )
        self.assertIsNone(svc._resolve_extension_timeout_seconds())  # pylint: disable=protected-access

        svc._config = SimpleNamespace(  # pylint: disable=protected-access
            mugen=SimpleNamespace(messaging=SimpleNamespace(extension_timeout_seconds=object()))
        )
        self.assertIsNone(svc._resolve_extension_timeout_seconds())  # pylint: disable=protected-access

        svc._config = SimpleNamespace(  # pylint: disable=protected-access
            mugen=SimpleNamespace(messaging=SimpleNamespace(extension_timeout_seconds="bad"))
        )
        self.assertIsNone(svc._resolve_extension_timeout_seconds())  # pylint: disable=protected-access

        svc._config = SimpleNamespace(  # pylint: disable=protected-access
            mugen=SimpleNamespace(messaging=SimpleNamespace(extension_timeout_seconds=0))
        )
        self.assertIsNone(svc._resolve_extension_timeout_seconds())  # pylint: disable=protected-access

    def test_composed_helpers_and_normalization_branches(self) -> None:
        svc = self._new_service()

        self.assertEqual(
            svc._build_composed_text_prompt(parts=[]),  # pylint: disable=protected-access
            "",
        )
        self.assertEqual(
            svc._build_composed_text_prompt(  # pylint: disable=protected-access
                parts=[
                    {"type": "unknown"},
                    {"type": "attachment", "id": " ", "caption": ""},
                ]
            ),
            "[attachment:unknown]",
        )
        self.assertIsNone(  # pylint: disable=protected-access
            svc._build_composed_attachment_context(attachments=[], composition_mode="x")
        )

        self.assertEqual(
            svc._infer_media_message_type("audio/ogg"),  # pylint: disable=protected-access
            "audio",
        )
        self.assertEqual(
            svc._infer_media_message_type("video/mp4"),  # pylint: disable=protected-access
            "video",
        )
        self.assertEqual(
            svc._infer_media_message_type("image/png"),  # pylint: disable=protected-access
            "image",
        )
        self.assertEqual(
            svc._infer_media_message_type("application/pdf"),  # pylint: disable=protected-access
            "file",
        )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(None)  # pylint: disable=protected-access

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": None,
                    "parts": [],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "",
                    "parts": [],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "bad",
                    "parts": [],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": "bad",
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": ["bad-item"],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": [
                        {
                            "id": "a1",
                            "file_path": "/tmp/a1",
                            "mime_type": "application/octet-stream",
                            "metadata": [],
                        }
                    ],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": [
                        {
                            "id": "a1",
                            "file_path": "/tmp/a1",
                        },
                        {
                            "id": "a1",
                            "file_path": "/tmp/a2",
                        },
                    ],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": "bad",
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": ["bad-item"],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [{"type": "bad"}],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [{"type": "attachment", "id": "a1"}],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
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
                            "file_path": "/tmp/a1",
                            "metadata": {},
                        }
                    ],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "attachment_with_caption",
                    "parts": [{"type": "text", "text": "bad"}],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "attachment_with_caption",
                    "parts": [],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "attachment_with_caption",
                    "parts": [{"type": "attachment", "id": "a1"}],
                    "attachments": [],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "attachment_with_caption",
                    "parts": [{"type": "attachment", "id": "a1"}],
                    "attachments": [
                        {
                            "id": "a1",
                            "file_path": "/tmp/a1",
                            "metadata": {},
                            "caption": None,
                        }
                    ],
                }
            )

        with self.assertRaises(ValueError):
            svc._normalize_composed_message(  # pylint: disable=protected-access
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [{"type": "text", "text": "ok"}],
                    "attachments": [],
                    "metadata": [],
                }
            )

        normalized_blank_text = svc._normalize_composed_message(  # pylint: disable=protected-access
            {
                "composition_mode": "message_with_attachments",
                "parts": [{"type": "text", "text": "   "}, {"type": "attachment", "id": "a1"}],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1",
                        "metadata": {},
                    }
                ],
            }
        )
        self.assertEqual(normalized_blank_text["parts"][0]["text"], "   ")

        normalized = svc._normalize_composed_message(  # pylint: disable=protected-access
            {
                "composition_mode": "message_with_attachments",
                "parts": [
                    {"type": "text", "text": "hello"},
                    {
                        "type": "attachment",
                        "id": "a1",
                        "caption": " part-cap ",
                        "metadata": {"part": "meta"},
                    },
                ],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1",
                        "mime_type": "APPLICATION/OCTET-STREAM",
                        "original_filename": 123,
                        "metadata": None,
                        "caption": " attachment-cap ",
                    }
                ],
                "metadata": {"top": "level"},
                "client_message_id": 987,
            }
        )
        self.assertEqual(normalized["composition_mode"], "message_with_attachments")
        self.assertEqual(normalized["attachments"][0]["mime_type"], "application/octet-stream")
        self.assertEqual(normalized["attachments"][0]["metadata"], {})
        self.assertEqual(normalized["attachments"][0]["original_filename"], "123")
        self.assertEqual(normalized["parts"][1]["caption"], "part-cap")
        self.assertEqual(normalized["parts"][1]["metadata"], {"part": "meta"})
        self.assertEqual(normalized["metadata"], {"top": "level"})
        self.assertEqual(normalized["client_message_id"], "987")

    def test_register_methods_update_all_extension_lists(self) -> None:
        svc = self._new_service()

        cp = Mock()
        ct = Mock()
        ctx = Mock()
        mh = Mock()
        rag = Mock()
        rpp = Mock()

        svc.register_cp_extension(cp)
        svc.register_ct_extension(ct)
        svc.register_ctx_extension(ctx)
        svc.register_mh_extension(mh)
        svc.register_rag_extension(rag)
        svc.register_rpp_extension(rpp)

        self.assertEqual(svc.cp_extensions, [cp])
        self.assertEqual(svc.ct_extensions, [ct])
        self.assertEqual(svc.ctx_extensions, [ctx])
        self.assertEqual(svc.mh_extensions, [mh])
        self.assertEqual(svc.rag_extensions, [rag])
        self.assertEqual(svc.rpp_extensions, [rpp])

    def test_extension_platform_key_returns_empty_tuple_for_non_list(self) -> None:
        svc = self._new_service()
        ext = SimpleNamespace(platforms="matrix")
        self.assertEqual(
            svc._extension_platform_key(ext),  # pylint: disable=protected-access
            tuple(),
        )

    def test_register_extension_rejects_instance_duplicate(self) -> None:
        svc = self._new_service()
        ext = SimpleNamespace(platforms=["matrix"])
        svc.register_cp_extension(ext)
        with self.assertRaises(ValueError):
            svc.register_cp_extension(ext)

    def test_register_extension_rejects_logical_duplicate(self) -> None:
        svc = self._new_service()

        class _LocalExtension:  # pylint: disable=too-few-public-methods
            def __init__(self) -> None:
                self.platforms = ["matrix"]

        first = _LocalExtension()
        second = _LocalExtension()
        svc.register_cp_extension(first)
        with self.assertRaises(ValueError):
            svc.register_cp_extension(second)
