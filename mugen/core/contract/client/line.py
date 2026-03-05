"""Provides an abstract base class for LINE platform clients."""

__all__ = ["ILineClient"]

from abc import ABC, abstractmethod
from typing import Any


class ILineClient(ABC):
    """An ABC for LINE Messaging API clients."""

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
    async def reply_messages(
        self,
        *,
        reply_token: str,
        messages: list[dict[str, Any]],
    ) -> dict | None:
        """Reply to an inbound LINE event using reply token."""

    @abstractmethod
    async def push_messages(
        self,
        *,
        to: str,
        messages: list[dict[str, Any]],
    ) -> dict | None:
        """Push one or more messages to a LINE user."""

    @abstractmethod
    async def multicast_messages(
        self,
        *,
        to: list[str],
        messages: list[dict[str, Any]],
    ) -> dict | None:
        """Multicast one or more messages to LINE users."""

    @abstractmethod
    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
        reply_token: str | None = None,
    ) -> dict | None:
        """Send a text message to a LINE user."""

    @abstractmethod
    async def send_image_message(
        self,
        *,
        recipient: str,
        image: dict[str, Any],
        reply_token: str | None = None,
    ) -> dict | None:
        """Send an image message to a LINE user."""

    @abstractmethod
    async def send_audio_message(
        self,
        *,
        recipient: str,
        audio: dict[str, Any],
        reply_token: str | None = None,
    ) -> dict | None:
        """Send an audio message to a LINE user."""

    @abstractmethod
    async def send_video_message(
        self,
        *,
        recipient: str,
        video: dict[str, Any],
        reply_token: str | None = None,
    ) -> dict | None:
        """Send a video message to a LINE user."""

    @abstractmethod
    async def send_file_message(
        self,
        *,
        recipient: str,
        file: dict[str, Any],
        reply_token: str | None = None,
    ) -> dict | None:
        """Send a file representation to a LINE user."""

    @abstractmethod
    async def send_raw_message(
        self,
        *,
        op: str,
        payload: dict[str, Any],
    ) -> dict | None:
        """Send provider-native outbound payload."""

    @abstractmethod
    async def download_media(
        self,
        *,
        message_id: str,
    ) -> dict[str, Any] | None:
        """Download media content for a LINE message id."""

    @abstractmethod
    async def get_profile(
        self,
        *,
        user_id: str,
    ) -> dict | None:
        """Resolve LINE user profile details."""

    @abstractmethod
    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        """Emit a best-effort processing signal to a LINE user."""
