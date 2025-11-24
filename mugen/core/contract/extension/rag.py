"""Provides an abstract base class for RAG extensions."""

__all__ = ["IRAGExtension"]

from abc import abstractmethod

from . import IExtensionBase


class IRAGExtension(IExtensionBase):
    """An ABC for RAG extensions."""

    @abstractmethod
    async def retrieve(
        self,
        sender: str,
        message: str,
        thread: dict,
    ) -> tuple[list[dict], list[dict]]:
        """Perform knowledge retrieval."""
