"""Provides an abstract base class for knowledge gateways."""

__all__ = ["IKnowledgeGateway"]

from abc import ABC, abstractmethod


class IKnowledgeGateway(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for knowledge retrival gateways."""

    @abstractmethod
    async def search_similar(  # pylint: disable=too-many-arguments
        self,
        collection_name: str,
        search_term: str,
        dataset: str = None,
        date_from: str = None,
        date_to: str = None,
        limit: int = 10,
        strategy: str = "must",
    ) -> list:
        """Search for documents in the knowledge base containing similar strings."""
