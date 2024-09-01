"""Provides an abstract base class for CT extensions."""

__all__ = ["ICTExtension"]

from abc import ABC, abstractmethod


class ICTExtension(ABC):
    """An ABC for CT extensions."""

    @property
    @abstractmethod
    def triggers(self) -> list[str]:
        """Get the list of triggers that activat the service provider."""

    @abstractmethod
    def get_context(self, user_id: str) -> list[dict]:
        """Provides conversation context through system messages."""

    # pylint: disable=too-many-arguments
    @abstractmethod
    async def process_message(
        self,
        message: str,
        role: str,
        room_id: str,
        user_id: str,
        chat_thread_key: str,
    ) -> None:
        """Process message for conversational triggers."""
