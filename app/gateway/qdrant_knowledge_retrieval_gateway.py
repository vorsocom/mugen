"""Provides a knowledge retrieval gateway for the Qdrant vector database."""

__all__ = ["QdrantKnowledgeRetrievalGateway"]

from sentence_transformers import SentenceTransformer
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException

from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.logging_gateway import ILoggingGateway

# encoder = SentenceTransformer("all-MiniLM-L6-v2")
encoder = SentenceTransformer("all-mpnet-base-v2")


class QdrantKnowledgeRetrievalGateway(IKnowledgeRetrievalGateway):
    """A knowledge retrieval gateway for the Qdrant vector database."""

    def __init__(
        self, api_key: str, endpoint_url: str, logging_gateway: ILoggingGateway
    ) -> None:
        self._client = AsyncQdrantClient(api_key=api_key, url=endpoint_url, port=None)
        self._logging_gateway = logging_gateway

    async def search_similar(
        self, collection_name: str, dataset: str, search_term: str
    ) -> list:
        self._logging_gateway.debug(
            f"qdrant_knowledge_retrieval_gateway: {search_term}"
        )
        try:
            return await self._client.search(
                collection_name=collection_name,
                query_vector=encoder.encode(search_term).tolist(),
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="dataset", match=models.MatchValue(value=dataset)
                        ),
                        models.FieldCondition(
                            key="data", match=models.MatchText(text=search_term)
                        ),
                    ]
                ),
                limit=10,
            )
        except ResponseHandlingException:
            self._logging_gateway.warning(
                "QdrantKnowledgeRetrievalGateway.search_similar:"
                " ResponseHandlingException"
            )
            return []
