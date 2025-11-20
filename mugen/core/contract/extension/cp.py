"""Provides an abstract base class for CP extensions."""

__all__ = ["ICPExtension"]

from abc import abstractmethod

from . import IExtensionBase


class ICPExtension(IExtensionBase):
    """An ABC for CP extensions."""

    @abstractmethod
    async def process_message(  # pylint: disable=too-many-arguments
        self,
        message: str,
        room_id: str,
        user_id: str,
    ) -> str | None:
        """Process message for commands."""
