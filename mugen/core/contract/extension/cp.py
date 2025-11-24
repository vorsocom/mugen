"""Provides an abstract base class for CP extensions."""

__all__ = ["ICPExtension"]

from abc import abstractmethod

from . import IExtensionBase


class ICPExtension(IExtensionBase):
    """An ABC for CP extensions."""

    @property
    @abstractmethod
    def commands(self) -> list[str]:
        """Get the commands that are processed by the extension."""

    @abstractmethod
    async def process_message(  # pylint: disable=too-many-arguments
        self,
        message: str,
        room_id: str,
        user_id: str,
    ) -> list[dict] | None:
        """Process message for commands."""
