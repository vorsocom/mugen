"""Provides a knowledge retrieval gateway for the Qdrant vector database."""

__all__ = ["QdrantKnowledgeRetrievalGateway"]

from sentence_transformers import SentenceTransformer
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException
import yake

from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.logging_gateway import ILoggingGateway

# encoder = SentenceTransformer("all-MiniLM-L6-v2")
encoder = SentenceTransformer("all-mpnet-base-v2")

keyword_extractor = yake.KeywordExtractor(
    lan="en", n=4, dedupLim=0.9, top=5, features=None
)


class QdrantKnowledgeRetrievalGateway(IKnowledgeRetrievalGateway):
    """A knowledge retrieval gateway for the Qdrant vector database."""

    def __init__(
        self, api_key: str, endpoint_url: str, logging_gateway: ILoggingGateway
    ) -> None:
        self._client = AsyncQdrantClient(api_key=api_key, url=endpoint_url, port=None)
        self._logging_gateway = logging_gateway

    async def search_similar(
        self,
        collection_name: str,
        dataset: str,
        search_term: str,
        strategy: str = "must",
    ) -> list:
        self._logging_gateway.debug(
            f"QdrantKnowledgeRetrievalGateway.search_similar: {search_term}"
        )
        conditions = []
        for keyword in keyword_extractor.extract_keywords(search_term):
            conditions.append(
                models.FieldCondition(
                    key="data", match=models.MatchText(text=keyword[0])
                )
            )
        # self._logging_gateway.debug(conditions)
        try:
            if strategy == "should":
                return await self._client.search(
                    collection_name=collection_name,
                    query_vector=encoder.encode(search_term).tolist(),
                    query_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="dataset", match=models.MatchValue(value=dataset)
                            )
                        ],
                        should=conditions,
                    ),
                    limit=10,
                )

            return await self._client.search(
                collection_name=collection_name,
                query_vector=encoder.encode(search_term).tolist(),
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="dataset", match=models.MatchValue(value=dataset)
                        )
                    ]
                    + conditions,
                ),
                limit=10,
            )
        except ResponseHandlingException:
            self._logging_gateway.warning(
                "QdrantKnowledgeRetrievalGateway.search_similar:"
                " ResponseHandlingException"
            )
            return []
