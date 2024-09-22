"""Provides an abstract base class for context extensions."""

__all__ = ["ICTXExtension"]

from abc import ABC, abstractmethod


class ICTXExtension(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for context extensions."""

    @property
    @abstractmethod
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""

    @abstractmethod
    def get_context(self, user_id: str) -> list[dict]:
        """Provides conversation context through system messages."""
