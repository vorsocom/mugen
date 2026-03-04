"""Provides an abstract base class for Telegram platform clients."""

__all__ = ["ITelegramClient"]

from abc import ABC, abstractmethod
from typing import Any


class ITelegramClient(ABC):
    """An ABC for Telegram Bot API clients."""

    @abstractmethod
    async def init(self) -> None:
        """Perform startup routine."""

    @abstractmethod
    async def verify_startup(self) -> bool:
        """Perform startup probe and return readiness result."""

    @abstractmethod
    async def close(self) -> None:
        """Perform shutdown routine."""

    @abstractmethod
    async def send_text_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        """Send a text message to a Telegram chat."""

    @abstractmethod
    async def send_audio_message(
        self,
        *,
        chat_id: str,
        audio: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        """Send an audio message to a Telegram chat."""

    @abstractmethod
    async def send_file_message(
        self,
        *,
        chat_id: str,
        document: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        """Send a document message to a Telegram chat."""

    @abstractmethod
    async def send_image_message(
        self,
        *,
        chat_id: str,
        photo: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        """Send an image message to a Telegram chat."""

    @abstractmethod
    async def send_video_message(
        self,
        *,
        chat_id: str,
        video: dict[str, Any],
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        """Send a video message to a Telegram chat."""

    @abstractmethod
    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool | None = None,
    ) -> dict | None:
        """Answer a Telegram callback query."""

    @abstractmethod
    async def emit_processing_signal(
        self,
        chat_id: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        """Emit a best-effort processing signal to a Telegram chat."""

    @abstractmethod
    async def download_media(self, file_id: str) -> dict[str, Any] | None:
        """Resolve and download Telegram media by file id."""
