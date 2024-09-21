"""Provides an abstract base class for knowledge retrieval gateways."""

__all__ = ["IKnowledgeRetrievalGateway"]

from abc import ABC, abstractmethod


class IKnowledgeRetrievalGateway(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for knowledge retrival gateways."""

    @abstractmethod
    async def search_similar(  # pylint: disable=too-many-arguments
        self,
        collection_name: str,
        search_term: str,
        dataset: str,
        date_from: str,
        date_to: str,
        limit: int,
        strategy: str,
    ) -> list:
        """Search for documents in the knowledge base containing similar strings."""
