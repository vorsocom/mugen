"""Unit tests for core LINE client contract defaults."""

import unittest

from mugen.core.contract.client.line import ILineClient


class _LineClientPort(ILineClient):
    async def init(self) -> None:
        return None

    async def verify_startup(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def reply_messages(
        self,
        *,
        reply_token: str,
        messages: list[dict],
    ) -> dict | None:
        _ = (reply_token, messages)
        return {"ok": True}

    async def push_messages(
        self,
        *,
        to: str,
        messages: list[dict],
    ) -> dict | None:
        _ = (to, messages)
        return {"ok": True}

    async def multicast_messages(
        self,
        *,
        to: list[str],
        messages: list[dict],
    ) -> dict | None:
        _ = (to, messages)
        return {"ok": True}

    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
        reply_token: str | None = None,
    ) -> dict | None:
        _ = (recipient, text, reply_token)
        return {"ok": True}

    async def send_image_message(
        self,
        *,
        recipient: str,
        image: dict,
        reply_token: str | None = None,
    ) -> dict | None:
        _ = (recipient, image, reply_token)
        return {"ok": True}

    async def send_audio_message(
        self,
        *,
        recipient: str,
        audio: dict,
        reply_token: str | None = None,
    ) -> dict | None:
        _ = (recipient, audio, reply_token)
        return {"ok": True}

    async def send_video_message(
        self,
        *,
        recipient: str,
        video: dict,
        reply_token: str | None = None,
    ) -> dict | None:
        _ = (recipient, video, reply_token)
        return {"ok": True}

    async def send_file_message(
        self,
        *,
        recipient: str,
        file: dict,
        reply_token: str | None = None,
    ) -> dict | None:
        _ = (recipient, file, reply_token)
        return {"ok": True}

    async def send_raw_message(
        self,
        *,
        op: str,
        payload: dict,
    ) -> dict | None:
        _ = (op, payload)
        return {"ok": True}

    async def download_media(
        self,
        *,
        message_id: str,
    ) -> dict | None:
        _ = message_id
        return {"path": "/tmp/file.bin"}

    async def get_profile(
        self,
        *,
        user_id: str,
    ) -> dict | None:
        _ = user_id
        return {"ok": True}

    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        _ = (recipient, state, message_id)
        return True


class _IncompleteLineClientPort(ILineClient):
    async def init(self) -> None:
        return None


class TestMugenContractClientLine(unittest.IsolatedAsyncioTestCase):
    """Validate required abstract methods on ILineClient."""

    async def test_required_line_methods_are_callable_on_complete_port(self) -> None:
        client = _LineClientPort()

        self.assertTrue(await client.verify_startup())
        self.assertEqual(
            await client.send_text_message(recipient="1", text="hello"),
            {"ok": True},
        )
        self.assertEqual(
            await client.download_media(message_id="m-1"),
            {"path": "/tmp/file.bin"},
        )

    async def test_incomplete_port_cannot_be_instantiated(self) -> None:
        with self.assertRaises(TypeError):
            _IncompleteLineClientPort()
