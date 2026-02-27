"""Provides a knowledge retrieval gateway for the Qdrant vector database."""

__all__ = ["QdrantKnowledgeGateway"]

import asyncio
from types import SimpleNamespace
from typing import Any

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sentence_transformers import SentenceTransformer

from mugen.core.contract.dto.qdrant.search import QdrantSearchVendorParams
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway, KnowledgeSearchResult
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class QdrantKnowledgeGateway(IKnowledgeGateway):
    """A knowledge retrieval gateway for the Qdrant vector database."""

    _default_encoder_model = "all-mpnet-base-v2"
    _default_encoder_max_concurrency = 4

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
        self._encoder: SentenceTransformer | None = None
        self._encoder_lock = asyncio.Lock()
        self._encoder_max_concurrency = self._resolve_encoder_max_concurrency()
        self._encode_semaphore = asyncio.Semaphore(self._encoder_max_concurrency)

        if self._resolve_encoder_preload() is True:
            self._encoder = self._build_encoder()

    def _build_encoder(self) -> SentenceTransformer:
        return SentenceTransformer(
            model_name_or_path=self._default_encoder_model,
            tokenizer_kwargs={
                "clean_up_tokenization_spaces": False,
            },
            cache_folder=self._config.transformers.hf.home,
        )

    def _resolve_encoder_preload(self) -> bool:
        raw_value = getattr(
            getattr(getattr(self._config, "qdrant", SimpleNamespace()), "encoder", None),
            "preload",
            False,
        )
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return False

    def _resolve_encoder_max_concurrency(self) -> int:
        raw_value = getattr(
            getattr(getattr(self._config, "qdrant", SimpleNamespace()), "encoder", None),
            "max_concurrency",
            self._default_encoder_max_concurrency,
        )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = self._default_encoder_max_concurrency
        if parsed <= 0:
            return self._default_encoder_max_concurrency
        return parsed

    async def _get_encoder(self) -> SentenceTransformer:
        if self._encoder is not None:
            return self._encoder

        async with self._encoder_lock:
            if self._encoder is None:
                self._encoder = self._build_encoder()
            return self._encoder

    async def _encode_search_term(self, search_term: str) -> list[float]:
        encoder = await self._get_encoder()
        async with self._encode_semaphore:
            vector = await asyncio.to_thread(encoder.encode, search_term)

        if hasattr(vector, "tolist") and callable(getattr(vector, "tolist")):
            return list(vector.tolist())
        if isinstance(vector, list):
            return [float(item) for item in vector]
        return [float(item) for item in list(vector)]

    @staticmethod
    def _normalise_vendor_item(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return dict(item)

        model_dump = getattr(item, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped

        as_dict = getattr(item, "dict", None)
        if callable(as_dict):
            dumped = as_dict()
            if isinstance(dumped, dict):
                return dumped

        if hasattr(item, "__dict__"):
            return dict(getattr(item, "__dict__", {}))

        return {"value": str(item)}

    @staticmethod
    def _count_result(value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, dict):
            raw_count = value.get("count")
            if isinstance(raw_count, int):
                return raw_count
        raw_count = getattr(value, "count", None)
        if isinstance(raw_count, int):
            return raw_count
        return None

    async def search(
        self,
        params: QdrantSearchVendorParams,
    ) -> KnowledgeSearchResult:
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

        try:
            if params.strategy == "should":
                if params.count:
                    count_result = await self._client.count(
                        collection_name=params.collection_name,
                        count_filter=models.Filter(should=conditions),
                        exact=True,
                    )
                    return KnowledgeSearchResult(
                        items=[],
                        total_count=self._count_result(count_result),
                        raw_vendor={"count_result": self._normalise_vendor_item(count_result)},
                    )

                query_vector = await self._encode_search_term(params.search_term)
                search_results = await self._client.search(
                    collection_name=params.collection_name,
                    query_vector=query_vector,
                    query_filter=models.Filter(
                        must=dataset_filter,
                        should=conditions,
                    ),
                    limit=params.limit,
                )
                return KnowledgeSearchResult(
                    items=[self._normalise_vendor_item(item) for item in search_results],
                    total_count=None,
                    raw_vendor={
                        "strategy": "should",
                        "count": False,
                    },
                )

            if params.count:
                count_result = await self._client.count(
                    collection_name=params.collection_name,
                    count_filter=models.Filter(must=conditions),
                    exact=True,
                )
                return KnowledgeSearchResult(
                    items=[],
                    total_count=self._count_result(count_result),
                    raw_vendor={"count_result": self._normalise_vendor_item(count_result)},
                )

            query_vector = await self._encode_search_term(params.search_term)
            search_results = await self._client.search(
                collection_name=params.collection_name,
                query_vector=query_vector,
                query_filter=models.Filter(must=conditions),
                limit=params.limit,
            )
            return KnowledgeSearchResult(
                items=[self._normalise_vendor_item(item) for item in search_results],
                total_count=None,
                raw_vendor={
                    "strategy": "must",
                    "count": False,
                },
            )
        except (ResponseHandlingException, UnexpectedResponse):
            self._logging_gateway.warning(
                "QdrantKnowledgeGateway - ResponseHandlingException"
            )
            return KnowledgeSearchResult(items=[], total_count=0, raw_vendor=None)
