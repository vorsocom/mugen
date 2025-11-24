"""Provides an abstract base class for messaging services."""

__all__ = ["IMessagingService"]

from abc import ABC, abstractmethod
from typing import Any

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension


# pylint: disable=too-many-public-methods
class IMessagingService(ABC):
    """An abstract base class for messaging services."""

    @property
    @abstractmethod
    def cp_extensions(self) -> list[ICPExtension]:
        """Get the list of Command Processor extensions
        registered with the service.
        """

    @property
    @abstractmethod
    def ct_extensions(self) -> list[ICTExtension]:
        """Get the list of Coversational Trigger extensions
        registered with the service.
        """

    @property
    @abstractmethod
    def ctx_extensions(self) -> list[ICTXExtension]:
        """Get the list of Context extensions
        registered with the service.
        """

    @property
    @abstractmethod
    def mh_extensions(self) -> list[IMHExtension]:
        """Get the list of Message Handler extensions
        registered with the service.
        """

    @property
    @abstractmethod
    def rag_extensions(self) -> list[IRAGExtension]:
        """Get the list of Retrieval Augmented Generation extensions
        registered with the service.
        """

    @property
    @abstractmethod
    def rpp_extensions(self) -> list[IRPPExtension]:
        """Get the list of Response Pre-Processor extensions
        registered with the service.
        """

    @abstractmethod
    async def handle_audio_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: Any,
    ) -> list[dict] | None:
        """Handle an audio message from a chat."""

    @abstractmethod
    async def handle_file_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: Any,
    ) -> list[dict] | None:
        """Handle a file message from a chat."""

    @abstractmethod
    async def handle_image_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message,
    ) -> list[dict] | None:
        """Handle an image message from a chat."""

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    @abstractmethod
    async def handle_text_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: str,
        message_context: list[str] = None,
    ) -> list[dict] | None:
        """Handle a text message from a chat."""

    @abstractmethod
    async def handle_video_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: Any,
    ) -> list[dict] | None:
        """Handle a video message from a chat."""

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
