"""Provides a knowledge retrieval gateway for the Qdrant vector database."""

__all__ = ["QdrantKnowledgeGateway"]

from types import SimpleNamespace

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException
from sentence_transformers import SentenceTransformer

from mugen.core.contract.dto.qdrant.search import QdrantSearchVendorParams
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class QdrantKnowledgeGateway(IKnowledgeGateway):
    """A knowledge retrieval gateway for the Qdrant vector database."""

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._client = AsyncQdrantClient(
            api_key=self._config.qdrant.api.key,
            url=self._config.qdrant.api.url,
            port=None,
        )
        self._logging_gateway = logging_gateway

        self._encoder = SentenceTransformer(
            model_name_or_path="all-mpnet-base-v2",
            tokenizer_kwargs={
                "clean_up_tokenization_spaces": False,
            },
            cache_folder=self._config.transformers.hf.home,
        )

    async def search(
        self,
        params: QdrantSearchVendorParams,
    ) -> list:
        self._logging_gateway.debug(
            f"QdrantKnowledgeGateway: Search terms {params.search_term}"
        )
        conditions = []
        dataset_filter = None
        # Restrict to dataset if specified.
        if params.dataset:
            dataset_filter = [
                models.FieldCondition(
                    key="dataset",
                    match=models.MatchValue(value=params.dataset),
                )
            ]
            if params.strategy == "must":
                conditions += dataset_filter

        # Add date constraints.
        if params.date_from and params.date_to:
            conditions.append(
                models.FieldCondition(
                    key="date",
                    range=models.DatetimeRange(
                        gte=params.date_from,
                        lte=params.date_to,
                    ),
                )
            )
        elif params.date_from and not params.date_to:
            conditions.append(
                models.FieldCondition(
                    key="date",
                    range=models.DatetimeRange(
                        gte=params.date_from,
                    ),
                )
            )
        elif params.date_to and not params.date_from:
            conditions.append(
                models.FieldCondition(
                    key="date",
                    range=models.DatetimeRange(
                        lte=params.date_to,
                    ),
                )
            )

        # Add keyword conditions.
        for keyword in params.keywords:
            conditions.append(
                models.FieldCondition(
                    key="data",
                    match=models.MatchText(text=keyword),
                )
            )
        # self._logging_gateway.debug(conditions)
        try:
            if params.strategy == "should":
                if params.count:
                    return await self._client.count(
                        collection_name=params.collection_name,
                        count_filter=models.Filter(should=conditions),
                        exact=True,
                    )

                return await self._client.search(
                    collection_name=params.collection_name,
                    query_vector=self._encoder.encode(params.search_term).tolist(),
                    query_filter=models.Filter(
                        must=dataset_filter,
                        should=conditions,
                    ),
                    limit=params.limit,
                )

            if params.count:
                return await self._client.count(
                    collection_name=params.collection_name,
                    count_filter=models.Filter(must=conditions),
                    exact=True,
                )

            return await self._client.search(
                collection_name=params.collection_name,
                query_vector=self._encoder.encode(params.search_term).tolist(),
                query_filter=models.Filter(must=conditions),
                limit=params.limit,
            )
        except ResponseHandlingException:
            self._logging_gateway.warning(
                "QdrantKnowledgeGateway - ResponseHandlingException"
            )
            return []
