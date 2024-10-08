"""Provides an abstract base class for message handler extensions."""

__all__ = ["IMHExtension"]

from abc import abstractmethod

from . import IExtensionBase


class IMHExtension(IExtensionBase):
    """An ABC for message handler extensions."""

    @property
    @abstractmethod
    def message_types(self) -> list[str]:
        """Get the list of message types that the extension handles."""

    @abstractmethod
    async def handle_message(self, room_id: str, sender: str, message) -> None:
        """Handle a message."""
