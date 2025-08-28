"""Provides an abstract base class for RAG extensions."""

__all__ = ["IRAGExtension"]

from abc import abstractmethod

from . import IExtensionBase


class IRAGExtension(IExtensionBase):
    """An ABC for RAG extensions."""

    @property
    @abstractmethod
    def cache_key(self) -> str:
        """Get key used to access the provider cache."""

    @abstractmethod
    async def retrieve(self, sender: str, message: str, thread: dict) -> None:
        """Perform knowledge retrieval."""
