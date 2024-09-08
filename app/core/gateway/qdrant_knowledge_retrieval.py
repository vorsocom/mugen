"""Provides a knowledge retrieval gateway for the Qdrant vector database."""

__all__ = ["QdrantKnowledgeRetrievalGateway"]

from types import SimpleNamespace

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException
from sentence_transformers import SentenceTransformer

from app.core.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.nlp_service import INLPService

encoder = SentenceTransformer(
    model_name_or_path="all-mpnet-base-v2",
    tokenizer_kwargs={
        "clean_up_tokenization_spaces": False,
    },
)


class QdrantKnowledgeRetrievalGateway(IKnowledgeRetrievalGateway):
    """A knowledge retrieval gateway for the Qdrant vector database."""

    def __init__(
        self,
        config: dict,
        logging_gateway: ILoggingGateway,
        nlp_service: INLPService,
    ) -> None:
        self._config = SimpleNamespace(**config)
        self._client = AsyncQdrantClient(
            api_key=self._config.qdrant_api_key,
            url=self._config.qdrant_endpoint_url,
            port=None,
        )
        self._logging_gateway = logging_gateway
        self._nlp_service = nlp_service

    # pylint: disable=too-many-arguments
    async def search_similar(
        self,
        collection_name: str,
        search_term: str,
        dataset: str = None,
        date_from: str = None,
        date_to: str = None,
        limit: int = 10,
        strategy: str = "must",
    ) -> list:
        self._logging_gateway.debug(
            f"QdrantKnowledgeRetrievalGateway.search_similar: search term {search_term}"
        )
        conditions = []
        dataset_filter = None
        # Restrict to dataset if specified.
        if dataset:
            dataset_filter = [
                models.FieldCondition(
                    key="dataset",
                    match=models.MatchValue(value=dataset),
                )
            ]
            if strategy == "must":
                conditions += dataset_filter

        # Add date constraints.
        if date_from and date_to:
            conditions.append(
                models.FieldCondition(
                    key="date",
                    range=models.DatetimeRange(
                        gte=date_from,
                        lte=date_to,
                    ),
                )
            )
        elif date_from and not date_to:
            conditions.append(
                models.FieldCondition(
                    key="date",
                    range=models.DatetimeRange(
                        gte=date_from,
                    ),
                )
            )
        elif date_to and not date_from:
            conditions.append(
                models.FieldCondition(
                    key="date",
                    range=models.DatetimeRange(
                        lte=date_to,
                    ),
                )
            )

        # Add keyword conditions.
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
                        must=dataset_filter,
                        should=conditions,
                    ),
                    limit=limit,
                )

            return await self._client.search(
                collection_name=collection_name,
                query_vector=encoder.encode(search_term).tolist(),
                query_filter=models.Filter(must=conditions),
                limit=limit,
            )
        except ResponseHandlingException:
            self._logging_gateway.warning(
                "QdrantKnowledgeRetrievalGateway.search_similar:"
                " ResponseHandlingException"
            )
            return []
