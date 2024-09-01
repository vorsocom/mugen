"""Provides an abstract base class for NLP services."""

__all__ = ["INLPService"]

from abc import ABC, abstractmethod


# pylint: disable=too-few-public-methods
class INLPService(ABC):
    """An ABC for NLP services."""

    @abstractmethod
    def get_keywords(self, text: str) -> list[str]:
        """Do keyword extraction on text."""
