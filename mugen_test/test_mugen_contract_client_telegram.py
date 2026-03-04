"""Unit tests for core Telegram client contract defaults."""

import unittest

from mugen.core.contract.client.telegram import ITelegramClient


class _TelegramClientPort(ITelegramClient):
    async def init(self) -> None:
        return None

    async def verify_startup(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def send_text_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        _ = (chat_id, text, reply_markup, reply_to_message_id)
        return {"ok": True}

    async def send_audio_message(
        self,
        *,
        chat_id: str,
        audio: dict,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        _ = (chat_id, audio, reply_to_message_id)
        return {"ok": True}

    async def send_file_message(
        self,
        *,
        chat_id: str,
        document: dict,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        _ = (chat_id, document, reply_to_message_id)
        return {"ok": True}

    async def send_image_message(
        self,
        *,
        chat_id: str,
        photo: dict,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        _ = (chat_id, photo, reply_to_message_id)
        return {"ok": True}

    async def send_video_message(
        self,
        *,
        chat_id: str,
        video: dict,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        _ = (chat_id, video, reply_to_message_id)
        return {"ok": True}

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool | None = None,
    ) -> dict | None:
        _ = (callback_query_id, text, show_alert)
        return {"ok": True}

    async def emit_processing_signal(
        self,
        chat_id: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        _ = (chat_id, state, message_id)
        return True

    async def download_media(self, file_id: str) -> dict | None:
        _ = file_id
        return {"path": "/tmp/file.bin"}


class _IncompleteTelegramClientPort(ITelegramClient):
    async def init(self) -> None:
        return None


class TestMugenContractClientTelegram(unittest.IsolatedAsyncioTestCase):
    """Validate required abstract methods on ITelegramClient."""

    async def test_required_telegram_methods_are_callable_on_complete_port(self) -> None:
        client = _TelegramClientPort()

        self.assertTrue(await client.verify_startup())
        self.assertEqual(
            await client.send_text_message(chat_id="1", text="hello"),
            {"ok": True},
        )
        self.assertEqual(
            await client.download_media("file-1"),
            {"path": "/tmp/file.bin"},
        )

    async def test_incomplete_port_cannot_be_instantiated(self) -> None:
        with self.assertRaises(TypeError):
            _IncompleteTelegramClientPort()
