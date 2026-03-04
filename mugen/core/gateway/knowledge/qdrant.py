"""Provides a knowledge retrieval gateway for the Qdrant vector database."""

__all__ = ["QdrantKnowledgeGateway"]

import asyncio
import inspect
from math import isfinite
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sentence_transformers import SentenceTransformer

from mugen.core.contract.dto.qdrant.search import QdrantSearchVendorParams
from mugen.core.contract.gateway.knowledge import (
    IKnowledgeGateway,
    KnowledgeGatewayRuntimeError,
    KnowledgeSearchResult,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.completion.timeout_config import require_fields_in_production
from mugen.core.utility.config_value import (
    parse_nonnegative_finite_float,
    parse_optional_positive_finite_float,
)


# pylint: disable=too-many-instance-attributes
class QdrantKnowledgeGateway(IKnowledgeGateway):
    """A knowledge retrieval gateway for the Qdrant vector database."""

    _default_encoder_model = "all-mpnet-base-v2"
    _default_encoder_max_concurrency = 4
    _default_api_max_retries = 0
    _default_api_retry_backoff_seconds = 0.5
    _default_search_top_k = 10
    _default_search_max_top_k = 50
    _default_snippet_max_chars = 240
    _required_payload_keys = (
        "tenant_id",
        "knowledge_entry_revision_id",
        "knowledge_pack_version_id",
        "channel",
        "locale",
        "category",
        "title",
        "body",
    )

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._closed = False

        self._api_key = self._resolve_optional_api_string("key")
        self._api_url = self._resolve_api_url()
        self._api_timeout_seconds = self._resolve_api_timeout_seconds()
        self._api_max_retries = self._resolve_api_max_retries()
        self._api_retry_backoff_seconds = self._resolve_api_retry_backoff_seconds()
        require_fields_in_production(
            config=self._config,
            provider_label="QdrantKnowledgeGateway",
            field_values={"timeout_seconds": self._api_timeout_seconds},
        )
        self._warn_missing_timeout_in_production()

        self._search_collection = self._resolve_search_collection()
        self._search_default_top_k = self._resolve_search_default_top_k()
        self._search_max_top_k = self._resolve_search_max_top_k()
        if self._search_default_top_k > self._search_max_top_k:
            self._logging_gateway.warning(
                "QdrantKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k."
            )
            self._search_default_top_k = self._search_max_top_k
        self._snippet_max_chars = self._resolve_snippet_max_chars()

        self._encoder: SentenceTransformer | None = None
        self._encoder_lock = asyncio.Lock()
        self._encoder_model_name = self._resolve_encoder_model_name()
        self._encoder_max_concurrency = self._resolve_encoder_max_concurrency()
        self._encode_semaphore = asyncio.Semaphore(self._encoder_max_concurrency)

        self._client = AsyncQdrantClient(
            api_key=self._api_key,
            url=self._api_url,
            port=None,
        )

    def _section(self, *path: str) -> object:
        node: object = self._config
        for key in path:
            node = getattr(node, key, None)
            if node is None:
                return None
        return node

    @staticmethod
    def _parse_positive_int(
        value: object,
        *,
        field_name: str,
        default: int,
    ) -> int:
        if value in [None, ""]:
            return default
        if isinstance(value, bool):
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be a positive integer."
            )
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be a positive integer."
            ) from exc
        if parsed <= 0:
            raise RuntimeError(
                f"Invalid configuration: {field_name} must be greater than 0."
            )
        return parsed

    def _resolve_api_url(self) -> str:
        raw_value = getattr(self._section("qdrant", "api"), "url", "")
        if not isinstance(raw_value, str):
            return ""
        return raw_value.strip()

    def _resolve_optional_api_string(self, key: str) -> str | None:
        raw_value = getattr(self._section("qdrant", "api"), key, None)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return normalized

    def _resolve_api_timeout_seconds(self) -> float | None:
        raw_value = getattr(self._section("qdrant", "api"), "timeout_seconds", None)
        return parse_optional_positive_finite_float(
            raw_value,
            "qdrant.api.timeout_seconds",
        )

    def _resolve_api_max_retries(self) -> int:
        raw_value = getattr(
            self._section("qdrant", "api"),
            "max_retries",
            self._default_api_max_retries,
        )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            self._logging_gateway.warning(
                "QdrantKnowledgeGateway: Invalid max_retries configuration."
            )
            return self._default_api_max_retries
        if parsed < 0:
            self._logging_gateway.warning(
                "QdrantKnowledgeGateway: max_retries must be non-negative."
            )
            return self._default_api_max_retries
        return parsed

    def _resolve_api_retry_backoff_seconds(self) -> float:
        raw_value = getattr(
            self._section("qdrant", "api"),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_value,
            field_name="qdrant.api.retry_backoff_seconds",
            default=self._default_api_retry_backoff_seconds,
        )

    def _resolve_search_collection(self) -> str:
        raw_value = getattr(self._section("qdrant", "search"), "collection", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError(
                "Invalid configuration: qdrant.search.collection is required."
            )
        return raw_value.strip()

    def _resolve_search_default_top_k(self) -> int:
        raw_value = getattr(
            self._section("qdrant", "search"),
            "default_top_k",
            self._default_search_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="qdrant.search.default_top_k",
            default=self._default_search_top_k,
        )

    def _resolve_search_max_top_k(self) -> int:
        raw_value = getattr(
            self._section("qdrant", "search"),
            "max_top_k",
            self._default_search_max_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="qdrant.search.max_top_k",
            default=self._default_search_max_top_k,
        )

    def _resolve_snippet_max_chars(self) -> int:
        raw_value = getattr(
            self._section("qdrant", "search"),
            "snippet_max_chars",
            self._default_snippet_max_chars,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="qdrant.search.snippet_max_chars",
            default=self._default_snippet_max_chars,
        )

    def _resolve_encoder_model_name(self) -> str:
        raw_model = getattr(
            self._section("qdrant", "encoder"),
            "model",
            self._default_encoder_model,
        )
        if not isinstance(raw_model, str):
            return self._default_encoder_model
        normalized = raw_model.strip()
        if normalized == "":
            return self._default_encoder_model
        return normalized

    def _resolve_encoder_max_concurrency(self) -> int:
        raw_value = getattr(
            self._section("qdrant", "encoder"),
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

    def _warn_missing_timeout_in_production(self) -> None:
        environment = str(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "environment", "")
        ).strip().lower()
        if environment != "production":
            return
        if self._api_timeout_seconds is None:
            self._logging_gateway.warning(
                "QdrantKnowledgeGateway: timeout_seconds is not configured in production."
            )

    def _build_encoder(self) -> SentenceTransformer:
        return SentenceTransformer(
            model_name_or_path=self._encoder_model_name,
            tokenizer_kwargs={
                "clean_up_tokenization_spaces": False,
            },
            cache_folder=getattr(self._section("transformers", "hf"), "home", None),
        )

    async def _get_encoder(self) -> SentenceTransformer:
        if self._encoder is not None:
            return self._encoder

        async with self._encoder_lock:
            if self._encoder is None:
                self._encoder = await asyncio.to_thread(self._build_encoder)
            return self._encoder

    async def _encode_search_term(self, search_term: str) -> list[float]:
        encoder = await self._get_encoder()
        async with self._encode_semaphore:
            vector = await asyncio.to_thread(encoder.encode, search_term)

        if hasattr(vector, "tolist") and callable(getattr(vector, "tolist")):
            return [float(item) for item in vector.tolist()]
        if isinstance(vector, list):
            return [float(item) for item in vector]
        return [float(item) for item in list(vector)]

    @staticmethod
    def _normalize_optional_filter(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if normalized == "":
            return None
        return normalized

    @staticmethod
    def _normalize_search_term(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("search_term must be a string")
        normalized = value.strip()
        if normalized == "":
            raise ValueError("search_term must be non-empty")
        return normalized

    @staticmethod
    def _normalize_tenant_id(value: object) -> str:
        if isinstance(value, uuid.UUID):
            return str(value)
        if not isinstance(value, str):
            raise ValueError("tenant_id must be a UUID.")
        parsed = uuid.UUID(value.strip())
        return str(parsed)

    def _resolve_effective_top_k(self, value: object) -> int:
        if value in [None, ""]:
            return self._search_default_top_k
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return self._search_default_top_k
        if parsed <= 0:
            return 1
        if parsed > self._search_max_top_k:
            return self._search_max_top_k
        return parsed

    @staticmethod
    def _normalize_min_similarity(value: object) -> float | None:
        if value in [None, ""]:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("min_similarity must be a float between 0 and 1.") from exc
        if isfinite(parsed) is not True:
            raise ValueError("min_similarity must be a float between 0 and 1.")
        if parsed < 0.0 or parsed > 1.0:
            raise ValueError("min_similarity must be a float between 0 and 1.")
        return parsed

    @staticmethod
    def _normalize_uuid_text(value: object, *, field_name: str) -> str:
        if isinstance(value, uuid.UUID):
            return str(value)
        if not isinstance(value, str):
            raise RuntimeError(
                f"Qdrant knowledge gateway payload field '{field_name}' must be a UUID string."
            )
        normalized = value.strip()
        if normalized == "":
            raise RuntimeError(
                f"Qdrant knowledge gateway payload field '{field_name}' must be a UUID string."
            )
        try:
            parsed = uuid.UUID(normalized)
        except (TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError(
                f"Qdrant knowledge gateway payload field '{field_name}' must be a UUID string."
            ) from exc
        return str(parsed)

    @staticmethod
    def _coerce_optional_string(value: object) -> str | None:
        if value in [None, ""]:
            return None
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _coerce_float(value: object) -> float | None:
        if value in [None, ""]:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_snippet(self, *, title: str | None, body: str | None) -> str | None:
        source = body if body not in [None, ""] else title
        if source in [None, ""]:
            return None
        text = str(source)
        if len(text) <= self._snippet_max_chars:
            return text
        return text[: self._snippet_max_chars]

    def _build_query_filter(
        self,
        *,
        tenant_id: str,
        channel: str | None,
        locale: str | None,
        category: str | None,
    ) -> models.Filter:
        must_conditions = [
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=tenant_id),
            )
        ]
        if channel is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="channel",
                    match=models.MatchValue(value=channel),
                )
            )
        if locale is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="locale",
                    match=models.MatchValue(value=locale),
                )
            )
        if category is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="category",
                    match=models.MatchValue(value=category),
                )
            )
        return models.Filter(must=must_conditions)

    @staticmethod
    def _extract_collection_names(collections_result: object) -> set[str]:
        collections = None
        if isinstance(collections_result, dict):
            collections = collections_result.get("collections")
        else:
            collections = getattr(collections_result, "collections", None)
        if not isinstance(collections, list):
            raise RuntimeError(
                "Qdrant knowledge gateway readiness probe returned an invalid payload."
            )

        names: set[str] = set()
        for item in collections:
            name = None
            if isinstance(item, dict):
                name = item.get("name")
            else:
                name = getattr(item, "name", None)
                if name in [None, ""] and isinstance(item, str):
                    name = item
            if isinstance(name, str) and name.strip() != "":
                names.add(name.strip())
        return names

    @staticmethod
    def _extract_points(search_result: object) -> list[Any]:
        if not isinstance(search_result, list):
            raise RuntimeError("Qdrant knowledge gateway returned an invalid search payload.")
        return list(search_result)

    @staticmethod
    def _extract_point_payload_and_score(point: object) -> tuple[dict[str, Any], object]:
        if isinstance(point, dict):
            payload = point.get("payload")
            if isinstance(payload, dict):
                return dict(payload), point.get("score")
            return dict(point), point.get("score")

        payload = getattr(point, "payload", None)
        score = getattr(point, "score", None)
        if isinstance(payload, dict):
            return dict(payload), score

        model_dump = getattr(point, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                payload = dumped.get("payload")
                if isinstance(payload, dict):
                    return dict(payload), dumped.get("score")

        raise RuntimeError("Qdrant knowledge gateway hit payload is invalid.")

    def _normalise_item(
        self,
        *,
        payload: dict[str, Any],
        score_raw: object,
    ) -> dict[str, Any]:
        missing_keys = sorted(
            key for key in self._required_payload_keys if key not in payload
        )
        if missing_keys:
            missing_text = ", ".join(missing_keys)
            raise RuntimeError(
                "Qdrant knowledge gateway payload is missing required key(s): "
                f"{missing_text}."
            )

        tenant_id = self._normalize_uuid_text(
            payload.get("tenant_id"),
            field_name="tenant_id",
        )
        revision_id = self._normalize_uuid_text(
            payload.get("knowledge_entry_revision_id"),
            field_name="knowledge_entry_revision_id",
        )
        version_id = self._normalize_uuid_text(
            payload.get("knowledge_pack_version_id"),
            field_name="knowledge_pack_version_id",
        )
        similarity = self._coerce_float(score_raw)
        title = self._coerce_optional_string(payload.get("title"))
        body = self._coerce_optional_string(payload.get("body"))
        return {
            "knowledge_entry_revision_id": revision_id,
            "knowledge_pack_version_id": version_id,
            "tenant_id": tenant_id,
            "channel": self._coerce_optional_string(payload.get("channel")),
            "locale": self._coerce_optional_string(payload.get("locale")),
            "category": self._coerce_optional_string(payload.get("category")),
            "title": title,
            "snippet": self._build_snippet(title=title, body=body),
            "similarity": similarity,
            "distance": None,
        }

    def _normalise_items(
        self,
        *,
        search_result: object,
        min_similarity: float | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for point in self._extract_points(search_result):
            payload, score_raw = self._extract_point_payload_and_score(point)
            item = self._normalise_item(payload=payload, score_raw=score_raw)
            if min_similarity is not None and (
                item["similarity"] is None
                or float(item["similarity"]) < float(min_similarity)
            ):
                continue
            items.append(item)
        return items

    async def _call_provider_method(
        self,
        method: Callable[..., object],
        /,
        *args,
        **kwargs,
    ) -> object:
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _query_collection(
        self,
        *,
        query_vector: list[float],
        query_filter: models.Filter,
        top_k: int,
    ) -> list[Any]:
        search = getattr(self._client, "search", None)
        if callable(search) is not True:
            raise RuntimeError("Qdrant knowledge gateway search API is unavailable.")

        search_result = await self._call_provider_method(
            search,
            collection_name=self._search_collection,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=top_k,
            **self._request_timeout_kwargs(),
        )
        return self._extract_points(search_result)

    async def _execute_with_retry(
        self,
        *,
        operation: str,
        request_factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        attempts = max(0, int(self._api_max_retries)) + 1
        for attempt in range(1, attempts + 1):
            try:
                return await request_factory()
            except (ResponseHandlingException, UnexpectedResponse, asyncio.TimeoutError) as exc:
                if attempt >= attempts:
                    raise
                delay_seconds = float(self._api_retry_backoff_seconds) * (2 ** (attempt - 1))
                self._logging_gateway.warning(
                    "QdrantKnowledgeGateway: transient %s failure; retrying "
                    "attempt=%d/%d delay_seconds=%.3f error=%s: %s"
                    % (
                        operation,
                        attempt,
                        attempts - 1,
                        delay_seconds,
                        type(exc).__name__,
                        exc,
                    )
                )
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
        return None

    def _request_timeout_kwargs(self) -> dict[str, float]:
        if self._api_timeout_seconds is None:
            return {}
        return {"timeout": self._api_timeout_seconds}

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Qdrant knowledge gateway is closed.")

    async def check_readiness(self) -> None:
        self._assert_open()
        if self._api_url == "":
            raise RuntimeError("Qdrant knowledge gateway requires qdrant.api.url.")

        probe = getattr(self._client, "get_collections", None)
        if callable(probe) is not True:
            raise RuntimeError("Qdrant knowledge gateway readiness probe is unavailable.")

        timeout_seconds = self._api_timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 5.0

        try:
            collections_result = await asyncio.wait_for(
                self._call_provider_method(probe),
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError("Qdrant knowledge gateway readiness probe failed.") from exc

        collection_names = self._extract_collection_names(collections_result)
        if self._search_collection not in collection_names:
            raise RuntimeError(
                "Qdrant knowledge gateway configured collection was not found."
            )

        try:
            await asyncio.wait_for(self._get_encoder(), timeout=timeout_seconds)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Qdrant knowledge gateway encoder initialization failed."
            ) from exc

    async def search(
        self,
        params: QdrantSearchVendorParams,
    ) -> KnowledgeSearchResult:
        self._assert_open()
        tenant_id = self._normalize_tenant_id(params.tenant_id)
        search_term = self._normalize_search_term(params.search_term)
        top_k = self._resolve_effective_top_k(params.top_k)
        min_similarity = self._normalize_min_similarity(params.min_similarity)
        channel = self._normalize_optional_filter(params.channel)
        locale = self._normalize_optional_filter(params.locale)
        category = self._normalize_optional_filter(params.category)
        query_vector = await self._encode_search_term(search_term)
        query_filter = self._build_query_filter(
            tenant_id=tenant_id,
            channel=channel,
            locale=locale,
            category=category,
        )

        try:
            raw_response = await self._execute_with_retry(
                operation="search",
                request_factory=lambda: self._query_collection(
                    query_vector=query_vector,
                    query_filter=query_filter,
                    top_k=top_k,
                ),
            )
            items = self._normalise_items(
                search_result=raw_response,
                min_similarity=min_similarity,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "QdrantKnowledgeGateway transport failure "
                f"(operation=search error={type(exc).__name__}: {exc})"
            )
            raise KnowledgeGatewayRuntimeError(
                provider="qdrant",
                operation="search",
                cause=exc,
            ) from exc

        return KnowledgeSearchResult(
            items=items,
            total_count=None,
            raw_vendor={
                "provider": "qdrant",
                "collection": self._search_collection,
                "result_count": len(items),
                "top_k": top_k,
                "min_similarity": min_similarity,
            },
        )

    async def aclose(self) -> None:
        if self._closed:
            return None
        self._closed = True
        close = getattr(self._client, "close", None)
        if callable(close):
            maybe_awaitable = close()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        self._client = None
        return None
