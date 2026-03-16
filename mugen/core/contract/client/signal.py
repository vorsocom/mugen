"""Provides an abstract base class for Signal platform clients."""

__all__ = ["ISignalClient"]

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class ISignalClient(ABC):
    """An ABC for Signal clients."""

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
    async def receive_events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield inbound Signal events from the receive stream."""

    @abstractmethod
    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
    ) -> dict | None:
        """Send a text message to a Signal recipient."""

    @abstractmethod
    async def send_media_message(
        self,
        *,
        recipient: str,
        message: str | None = None,
        base64_attachments: list[str] | None = None,
    ) -> dict | None:
        """Send a media message to a Signal recipient."""

    @abstractmethod
    async def send_reaction(
        self,
        *,
        recipient: str,
        reaction: str,
        target_author: str,
        timestamp: int,
        remove: bool = False,
    ) -> dict | None:
        """Send or remove a Signal reaction."""

    @abstractmethod
    async def send_receipt(
        self,
        *,
        recipient: str,
        receipt_type: str,
        timestamp: int,
    ) -> dict | None:
        """Send a Signal receipt."""

    @abstractmethod
    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        """Emit a best-effort processing signal to a Signal recipient."""

    @abstractmethod
    async def download_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        """Download attachment data by Signal attachment id."""
