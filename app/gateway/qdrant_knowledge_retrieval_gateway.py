"""Provides a knowledge retrieval gateway for the Qdrant vector database."""

__all__ = ["QdrantKnowledgeRetrievalGateway"]

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException
from sentence_transformers import SentenceTransformer

from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.nlp_service import INLPService

# encoder = SentenceTransformer("all-MiniLM-L6-v2")
encoder = SentenceTransformer("all-mpnet-base-v2")


class QdrantKnowledgeRetrievalGateway(IKnowledgeRetrievalGateway):
    """A knowledge retrieval gateway for the Qdrant vector database."""

    def __init__(
        self,
        api_key: str,
        endpoint_url: str,
        logging_gateway: ILoggingGateway,
        nlp_service: INLPService,
    ) -> None:
        self._client = AsyncQdrantClient(api_key=api_key, url=endpoint_url, port=None)
        self._logging_gateway = logging_gateway
        self._nlp_service = nlp_service

    async def search_similar(
        self,
        collection_name: str,
        dataset: str,
        search_term: str,
        strategy: str = "must",
    ) -> list:
        self._logging_gateway.debug(
            f"QdrantKnowledgeRetrievalGateway.search_similar: search term {search_term}"
        )
        conditions = []
        keywords = self._nlp_service.get_keywords(search_term)
        self._logging_gateway.debug(
            f"QdrantKnowledgeRetrievalGateway.search_similar: keywords {keywords}"
        )
        for keyword in keywords:
            conditions.append(
                models.FieldCondition(key="data", match=models.MatchText(text=keyword))
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
