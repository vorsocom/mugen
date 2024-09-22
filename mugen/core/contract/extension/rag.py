"""Provides an abstract base class for RAG extensions."""

__all__ = ["IRAGExtension"]

from abc import ABC, abstractmethod


class IRAGExtension(ABC):
    """An ABC for RAG extensions."""

    @property
    @abstractmethod
    def cache_key(self) -> str:
        """Get key used to access the provider cache."""

    @property
    @abstractmethod
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""

    @abstractmethod
    async def retrieve(self, sender: str, message: str) -> None:
        """Perform knowledge retrieval."""
