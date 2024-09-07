"""Provides an abstract base class for knowledge retrieval gateways."""

__all__ = ["IKnowledgeRetrievalGateway"]

from abc import ABC, abstractmethod


# pylint: disable=too-few-public-methods
class IKnowledgeRetrievalGateway(ABC):
    """An ABC for knowledge retrival gateways."""

    # pylint: disable=too-many-arguments
    @abstractmethod
    async def search_similar(
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
