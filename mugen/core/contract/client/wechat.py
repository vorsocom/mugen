"""Provides an abstract base class for WeChat clients."""

__all__ = ["IWeChatClient"]

from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any


class IWeChatClient(ABC):
    """An ABC for WeChat clients."""

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
        recipient: str,
        text: str,
        reply_to: str | None = None,
    ) -> dict | None:
        """Send a text message to a WeChat recipient."""

    @abstractmethod
    async def send_audio_message(
        self,
        *,
        recipient: str,
        audio: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        """Send an audio message to a WeChat recipient."""

    @abstractmethod
    async def send_file_message(
        self,
        *,
        recipient: str,
        file: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        """Send a file message to a WeChat recipient."""

    @abstractmethod
    async def send_image_message(
        self,
        *,
        recipient: str,
        image: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        """Send an image message to a WeChat recipient."""

    @abstractmethod
    async def send_video_message(
        self,
        *,
        recipient: str,
        video: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        """Send a video message to a WeChat recipient."""

    @abstractmethod
    async def send_raw_message(self, *, payload: dict[str, Any]) -> dict | None:
        """Send a provider-native payload."""

    @abstractmethod
    async def upload_media(
        self,
        *,
        file_path: str | BytesIO,
        media_type: str,
    ) -> dict | None:
        """Upload media to WeChat."""

    @abstractmethod
    async def download_media(
        self,
        *,
        media_id: str,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Download media from WeChat."""

    @abstractmethod
    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        """Emit a best-effort processing signal to a WeChat recipient."""
