"""Provides an abstract base class for RPP extensions."""

__all__ = ["IRPPExtension"]

from abc import ABC, abstractmethod


# pylint: disable=too-few-public-methods
class IRPPExtension(ABC):
    """An ABC for RPP extensions."""

    @abstractmethod
    async def preprocess_response(self, response: str) -> tuple[str, bool, bool]:
        """Preprocess the assistant response."""
