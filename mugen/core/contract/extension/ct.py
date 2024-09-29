"""Provides an abstract base class for CT extensions."""

__all__ = ["ICTExtension"]

from abc import ABC, abstractmethod


class ICTExtension(ABC):
    """An ABC for CT extensions."""

    @property
    @abstractmethod
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""

    @property
    @abstractmethod
    def triggers(self) -> list[str]:
        """Get the list of triggers that activate the service provider."""

    @abstractmethod
    def get_context(self, user_id: str) -> list[dict]:
        """Provides conversation context through system messages."""

    @abstractmethod
    async def process_message(  # pylint: disable=too-many-arguments
        self,
        message: str,
        role: str,
        room_id: str,
        user_id: str,
    ) -> None:
        """Process message for conversational triggers."""
