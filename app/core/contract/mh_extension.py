"""Provides an abstract base class for message handler extensions."""

__all__ = ["IMHExtension"]

from abc import ABC, abstractmethod


# pylint: disable=too-few-public-methods
class IMHExtension(ABC):
    """An ABC for message handler extensions."""

    @property
    @abstractmethod
    def message_types(self) -> list[str]:
        """Get the list of message types that the extension handles."""

    @property
    @abstractmethod
    def platform(self) -> str:
        """Get the platform that the extension is targeting."""

    @abstractmethod
    async def handle_message(self, room_id: str, sender: str, message) -> None:
        """Handle a message."""
