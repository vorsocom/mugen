"""Provides an abstract base class for messaging services."""

__all__ = ["IMessagingService"]

from abc import ABC, abstractmethod

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension


# pylint: disable=too-many-public-methods
class IMessagingService(ABC):
    """An abstract base class for messaging services."""

    @abstractmethod
    def bind_cp_extension(self, ext: ICPExtension, *, critical: bool = False) -> None:
        """Bind a CP extension to the service runtime."""

    @abstractmethod
    def bind_ct_extension(self, ext: ICTExtension, *, critical: bool = False) -> None:
        """Bind a CT extension to the service runtime."""

    @abstractmethod
    def bind_ctx_extension(self, ext: ICTXExtension, *, critical: bool = False) -> None:
        """Bind a CTX extension to the service runtime."""

    @abstractmethod
    def bind_mh_extension(self, ext: IMHExtension, *, critical: bool = False) -> None:
        """Bind an MH extension to the service runtime."""

    @abstractmethod
    def bind_rag_extension(self, ext: IRAGExtension, *, critical: bool = False) -> None:
        """Bind a RAG extension to the service runtime."""

    @abstractmethod
    def bind_rpp_extension(self, ext: IRPPExtension, *, critical: bool = False) -> None:
        """Bind an RPP extension to the service runtime."""

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
        message: dict,
    ) -> list[dict] | None:
        """Handle an audio message from a chat."""

    @abstractmethod
    async def handle_composed_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
        message_context: list[dict] | None = None,
    ) -> list[dict] | None:
        """Handle a composed message from a chat."""

    @abstractmethod
    async def handle_file_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        """Handle a file message from a chat."""

    @abstractmethod
    async def handle_image_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
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
        message_context: list[dict] | None = None,
    ) -> list[dict] | None:
        """Handle a text message from a chat."""

    @abstractmethod
    async def handle_video_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        """Handle a video message from a chat."""
