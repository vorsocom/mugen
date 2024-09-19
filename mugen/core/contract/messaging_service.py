"""Provides an abstract base class for messaging services."""

__all__ = ["IMessagingService"]

from abc import ABC, abstractmethod

from mugen.core.contract.ct_extension import ICTExtension
from mugen.core.contract.ctx_extension import ICTXExtension
from mugen.core.contract.mh_extension import IMHExtension
from mugen.core.contract.rag_extension import IRAGExtension
from mugen.core.contract.rpp_extension import IRPPExtension


class IMessagingService(ABC):
    """An abstract base class for messaging services."""

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
    def get_attention_thread_key(
        self,
        room_id: str,
        refresh: bool = False,
        start_task: bool = False,
    ) -> str:
        """Get the keyval storage key of the chat thread for a room."""

    @property
    @abstractmethod
    def mh_extensions(self) -> list[IMHExtension]:
        """Get the list of Message Handler extensions registered with the service."""

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
