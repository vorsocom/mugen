"""Provides an abstract base class for messaging services."""

__all__ = ["IMessagingService"]

from abc import ABC, abstractmethod
from app.core.contract.rag_extension import IRAGExtension
from app.core.contract.ct_extension import ICTExtension


class IMessagingService(ABC):
    """An abstract base class for messaging services."""

    @abstractmethod
    async def handle_text_message(
        self,
        room_id: str,
        sender: str,
        content: str,
    ) -> str | None:
        """Handle a text message from a chat."""

    @abstractmethod
    def register_ct_extension(self, ext: ICTExtension) -> None:
        """Register a CT extension with the messaging service."""

    @abstractmethod
    def register_rag_extension(self, ext: IRAGExtension) -> None:
        """Register an RAG extension with the messaging service."""
