"""Provides an abstract base class for Web platform clients."""

__all__ = ["IWebClient"]

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class IWebClient(ABC):
    """An ABC for Web platform clients."""

    @abstractmethod
    async def init(self) -> None:
        """Perform startup routine."""

    @abstractmethod
    async def close(self) -> None:
        """Perform shutdown routine."""

    @abstractmethod
    async def wait_until_stopped(self) -> None:
        """Block until the runtime loop exits or fails."""

    @abstractmethod
    async def enqueue_message(  # pylint: disable=too-many-arguments
        self,
        *,
        auth_user: str,
        conversation_id: str,
        message_type: str,
        text: str | None = None,
        metadata: dict[str, Any] | None = None,
        file_path: str | None = None,
        mime_type: str | None = None,
        original_filename: str | None = None,
        client_message_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist and enqueue a user message for asynchronous processing."""

    @abstractmethod
    async def stream_events(
        self,
        *,
        auth_user: str,
        conversation_id: str,
        last_event_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream replay and live SSE events for a conversation."""

    @abstractmethod
    async def resolve_media_download(
        self,
        *,
        auth_user: str,
        token: str,
    ) -> dict[str, Any] | None:
        """Resolve a media token to a downloadable asset for the user."""
