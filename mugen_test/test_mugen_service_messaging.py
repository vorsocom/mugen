"""Unit tests for mugen.core.service.messaging.DefaultMessagingService."""

import unittest
from unittest.mock import AsyncMock, Mock

from mugen.core.service.messaging import DefaultMessagingService


class _DummyMhExt:
    def __init__(self, *, platforms, message_types, response):
        self._platforms = set(platforms)
        self.message_types = message_types
        self._response = response
        self.handle_message = AsyncMock(side_effect=self._handle)

    def platform_supported(self, platform: str) -> bool:
        return platform in self._platforms

    async def _handle(self, **_kwargs):
        return self._response


class TestMugenServiceMessaging(unittest.IsolatedAsyncioTestCase):
    """Tests message handler fanout and extension registration."""

    def _new_service(self) -> DefaultMessagingService:
        svc = DefaultMessagingService(
            config=Mock(),
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
            message_context=["ctx"],
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
