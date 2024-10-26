"""Provides an abstract base class for RPP extensions."""

__all__ = ["IRPPExtension"]

from abc import abstractmethod

from . import IExtensionBase


class IRPPExtension(IExtensionBase):  # pylint: disable=too-few-public-methods
    """An ABC for RPP extensions."""

    @abstractmethod
    async def preprocess_response(
        self,
        room_id: str,
        user_id: str,
    ) -> str:
        """Preprocess the assistant response."""
