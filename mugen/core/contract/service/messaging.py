"""Provides an abstract base class for messaging services."""

__all__ = ["IMessagingService"]

from abc import ABC, abstractmethod

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension


class IMessagingService(ABC):
    """An abstract base class for messaging services."""

    @property
    @abstractmethod
    def mh_extensions(self) -> list[IMHExtension]:
        """Get the list of Message Handler extensions registered with the service."""

    @abstractmethod
    async def handle_text_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        content: str,
    ) -> str | None:
        """Handle a text message from a chat."""

    @abstractmethod
    def add_message_to_history(self, message: str, role: str, room_id: str) -> None:
        """Add a message to a room's chat history."""

    @abstractmethod
    def clear_chat_history(self, room_id: str, keep: int = 0) -> None:
        """Clear a room's chat history."""

    @abstractmethod
    def load_chat_history(self, room_id: str) -> dict:
        """Get a room's chat history from storage."""

    @abstractmethod
    def save_chat_history(self, room_id: str, history: dict) -> None:
        """Persist a room's chat history."""

    @abstractmethod
    def register_cp_extension(self, ext: ICPExtension) -> None:
        """Register a Command Processor (CP) extension."""

    @abstractmethod
    def register_ct_extension(self, ext: ICTExtension) -> None:
        """Register a Coversational Trigger (CT) extension."""

    @abstractmethod
    def register_ctx_extension(self, ext: ICTXExtension) -> None:
        """Register a Context (CTX) extension."""

    @abstractmethod
    def register_mh_extension(self, ext: IMHExtension) -> None:
        """Register a Message Handler (MH) extension."""

    @abstractmethod
    def register_rag_extension(self, ext: IRAGExtension) -> None:
        """Register a Retrieval Augmented Generation (RAG) extension."""

    @abstractmethod
    def register_rpp_extension(self, ext: IRPPExtension) -> None:
        """Register a Response Pre-Processor (RPP) extension."""
