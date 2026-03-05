"""Unit tests for core WeChat client contract defaults."""

import unittest

from mugen.core.contract.client.wechat import IWeChatClient


class _WeChatClientPort(IWeChatClient):
    async def init(self) -> None:
        return None

    async def verify_startup(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
        reply_to: str | None = None,
    ) -> dict | None:
        _ = (recipient, text, reply_to)
        return {"ok": True}

    async def send_audio_message(
        self,
        *,
        recipient: str,
        audio: dict,
        reply_to: str | None = None,
    ) -> dict | None:
        _ = (recipient, audio, reply_to)
        return {"ok": True}

    async def send_file_message(
        self,
        *,
        recipient: str,
        file: dict,
        reply_to: str | None = None,
    ) -> dict | None:
        _ = (recipient, file, reply_to)
        return {"ok": True}

    async def send_image_message(
        self,
        *,
        recipient: str,
        image: dict,
        reply_to: str | None = None,
    ) -> dict | None:
        _ = (recipient, image, reply_to)
        return {"ok": True}

    async def send_video_message(
        self,
        *,
        recipient: str,
        video: dict,
        reply_to: str | None = None,
    ) -> dict | None:
        _ = (recipient, video, reply_to)
        return {"ok": True}

    async def send_raw_message(self, *, payload: dict) -> dict | None:
        _ = payload
        return {"ok": True}

    async def upload_media(
        self,
        *,
        file_path,
        media_type: str,
    ) -> dict | None:
        _ = (file_path, media_type)
        return {"ok": True}

    async def download_media(
        self,
        *,
        media_id: str,
        mime_type: str | None = None,
    ) -> dict | None:
        _ = (media_id, mime_type)
        return {"path": "/tmp/file.bin"}

    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        _ = (recipient, state, message_id)
        return True


class _IncompleteWeChatClientPort(IWeChatClient):
    async def init(self) -> None:
        return None


class TestMugenContractClientWeChat(unittest.IsolatedAsyncioTestCase):
    """Validate required abstract methods on IWeChatClient."""

    async def test_required_methods_callable_on_complete_port(self) -> None:
        client = _WeChatClientPort()

        self.assertTrue(await client.verify_startup())
        self.assertEqual(
            await client.send_text_message(recipient="u1", text="hello"),
            {"ok": True},
        )
        self.assertEqual(
            await client.download_media(media_id="m-1"),
            {"path": "/tmp/file.bin"},
        )

    async def test_incomplete_port_cannot_be_instantiated(self) -> None:
        with self.assertRaises(TypeError):
            _IncompleteWeChatClientPort()

