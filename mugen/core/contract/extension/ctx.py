"""Provides an abstract base class for context extensions."""

__all__ = ["ICTXExtension"]

from abc import abstractmethod

from . import IExtensionBase


class ICTXExtension(IExtensionBase):  # pylint: disable=too-few-public-methods
    """An ABC for context extensions."""

    @abstractmethod
    def get_context(self, user_id: str) -> list[dict]:
        """Provides conversation context through system messages."""
