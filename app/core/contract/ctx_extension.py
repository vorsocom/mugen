"""Provides an abstract base class for context extensions."""

__all__ = ["ICTXExtension"]

from abc import ABC, abstractmethod


# pylint: disable=too-few-public-methods
class ICTXExtension(ABC):
    """An ABC for context extensions."""

    @abstractmethod
    def get_context(self, user_id: str) -> list[dict]:
        """Provides conversation context through system messages."""
