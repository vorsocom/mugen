"""Provides a knowledge retrieval gateway for Pinecone vector indexes."""

__all__ = ["PineconeKnowledgeGateway"]

import asyncio
import inspect
from math import isfinite
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from sentence_transformers import SentenceTransformer

from mugen.core.contract.dto.pinecone.search import PineconeSearchVendorParams
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
class PineconeKnowledgeGateway(IKnowledgeGateway):
    """A knowledge retrieval gateway for Pinecone vector indexes."""

    _default_encoder_model = "all-mpnet-base-v2"
    _default_encoder_max_concurrency = 4
    _default_api_max_retries = 0
    _default_api_retry_backoff_seconds = 0.5
    _default_search_metric = "cosine"
    _default_search_top_k = 10
    _default_search_max_top_k = 50
    _default_snippet_max_chars = 240
    _required_metadata_keys = (
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

        self._api_key = self._resolve_api_key()
        self._api_host = self._resolve_api_host()
        self._api_timeout_seconds = self._resolve_api_timeout_seconds()
        self._api_max_retries = self._resolve_api_max_retries()
        self._api_retry_backoff_seconds = self._resolve_api_retry_backoff_seconds()
        require_fields_in_production(
            config=self._config,
            provider_label="PineconeKnowledgeGateway",
            field_values={"timeout_seconds": self._api_timeout_seconds},
        )
        self._warn_missing_timeout_in_production()

        self._search_namespace = self._resolve_search_namespace()
        self._search_metric = self._resolve_search_metric()
        self._search_default_top_k = self._resolve_search_default_top_k()
        self._search_max_top_k = self._resolve_search_max_top_k()
        if self._search_default_top_k > self._search_max_top_k:
            self._logging_gateway.warning(
                "PineconeKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k."
            )
            self._search_default_top_k = self._search_max_top_k
        self._snippet_max_chars = self._resolve_snippet_max_chars()

        self._encoder: SentenceTransformer | None = None
        self._encoder_lock = asyncio.Lock()
        self._encoder_model_name = self._resolve_encoder_model_name()
        self._encoder_max_concurrency = self._resolve_encoder_max_concurrency()
        self._encode_semaphore = asyncio.Semaphore(self._encoder_max_concurrency)

        self._client = None
        self._client_lock = asyncio.Lock()
        self._index = None
        self._index_lock = asyncio.Lock()

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

    def _resolve_api_key(self) -> str:
        raw_value = getattr(self._section("pinecone", "api"), "key", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError("Invalid configuration: pinecone.api.key is required.")
        return raw_value.strip()

    def _resolve_api_host(self) -> str:
        raw_value = getattr(self._section("pinecone", "api"), "host", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError("Invalid configuration: pinecone.api.host is required.")
        return raw_value.strip()

    def _resolve_api_timeout_seconds(self) -> float | None:
        raw_value = getattr(self._section("pinecone", "api"), "timeout_seconds", None)
        return parse_optional_positive_finite_float(
            raw_value,
            "pinecone.api.timeout_seconds",
        )

    def _resolve_api_max_retries(self) -> int:
        raw_value = getattr(
            self._section("pinecone", "api"),
            "max_retries",
            self._default_api_max_retries,
        )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            self._logging_gateway.warning(
                "PineconeKnowledgeGateway: Invalid max_retries configuration."
            )
            return self._default_api_max_retries
        if parsed < 0:
            self._logging_gateway.warning(
                "PineconeKnowledgeGateway: max_retries must be non-negative."
            )
            return self._default_api_max_retries
        return parsed

    def _resolve_api_retry_backoff_seconds(self) -> float:
        raw_value = getattr(
            self._section("pinecone", "api"),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_value,
            field_name="pinecone.api.retry_backoff_seconds",
            default=self._default_api_retry_backoff_seconds,
        )

    def _resolve_search_namespace(self) -> str | None:
        raw_value = getattr(self._section("pinecone", "search"), "namespace", None)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return normalized

    def _resolve_search_metric(self) -> str:
        raw_value = getattr(
            self._section("pinecone", "search"),
            "metric",
            self._default_search_metric,
        )
        if not isinstance(raw_value, str):
            return self._default_search_metric
        normalized = raw_value.strip().lower()
        if normalized == "":
            return self._default_search_metric
        if normalized not in {"cosine", "dotproduct", "euclidean"}:
            raise RuntimeError(
                "Invalid configuration: pinecone.search.metric must be one of "
                "cosine, dotproduct, euclidean."
            )
        return normalized

    def _resolve_search_default_top_k(self) -> int:
        raw_value = getattr(
            self._section("pinecone", "search"),
            "default_top_k",
            self._default_search_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="pinecone.search.default_top_k",
            default=self._default_search_top_k,
        )

    def _resolve_search_max_top_k(self) -> int:
        raw_value = getattr(
            self._section("pinecone", "search"),
            "max_top_k",
            self._default_search_max_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="pinecone.search.max_top_k",
            default=self._default_search_max_top_k,
        )

    def _resolve_snippet_max_chars(self) -> int:
        raw_value = getattr(
            self._section("pinecone", "search"),
            "snippet_max_chars",
            self._default_snippet_max_chars,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="pinecone.search.snippet_max_chars",
            default=self._default_snippet_max_chars,
        )

    def _resolve_encoder_model_name(self) -> str:
        raw_value = getattr(
            self._section("pinecone", "encoder"),
            "model",
            self._default_encoder_model,
        )
        if not isinstance(raw_value, str):
            return self._default_encoder_model
        normalized = raw_value.strip()
        if normalized == "":
            return self._default_encoder_model
        return normalized

    def _resolve_encoder_max_concurrency(self) -> int:
        raw_value = getattr(
            self._section("pinecone", "encoder"),
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

    @staticmethod
    def _create_client(*, api_key: str):
        # pylint: disable=import-outside-toplevel
        try:
            from pinecone import PineconeAsyncio

            return PineconeAsyncio(api_key=api_key)
        except (ImportError, AttributeError):
            from pinecone import Pinecone

            return Pinecone(api_key=api_key)

    async def _get_client(self):
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = self._create_client(api_key=self._api_key)
            return self._client

    @staticmethod
    async def _call_provider_method(
        method: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if inspect.iscoroutinefunction(method):
            return await method(*args, **kwargs)
        result = await asyncio.to_thread(method, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    async def _await_with_timeout(
        maybe_awaitable: Awaitable[Any],
        *,
        timeout_seconds: float | None,
    ) -> Any:
        if timeout_seconds is None:
            return await maybe_awaitable
        return await asyncio.wait_for(maybe_awaitable, timeout=timeout_seconds)

    async def _build_index(self):
        client = await self._get_client()
        index_factory = getattr(client, "IndexAsyncio", None)
        if callable(index_factory) is not True:
            index_factory = getattr(client, "Index", None)
        if callable(index_factory) is not True:
            raise RuntimeError(
                "Pinecone knowledge gateway index factory is unavailable."
            )
        try:
            return await self._call_provider_method(
                index_factory,
                host=self._api_host,
            )
        except TypeError:
            return await self._call_provider_method(index_factory, self._api_host)

    async def _get_index(self):
        if self._index is not None:
            return self._index
        async with self._index_lock:
            if self._index is None:
                self._index = await self._build_index()
            return self._index

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
                "Pinecone knowledge gateway metadata field "
                f"'{field_name}' must be a UUID string."
            )
        normalized = value.strip()
        if normalized == "":
            raise RuntimeError(
                "Pinecone knowledge gateway metadata field "
                f"'{field_name}' must be a UUID string."
            )
        try:
            parsed = uuid.UUID(normalized)
        except (TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError(
                "Pinecone knowledge gateway metadata field "
                f"'{field_name}' must be a UUID string."
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

    def _normalize_similarity_distance(self, score_raw: object) -> tuple[float | None, float | None]:
        score = self._coerce_float(score_raw)
        if score is None:
            return None, None
        if self._search_metric == "cosine":
            return score, float(1.0 - score)
        if self._search_metric in {"dotproduct", "euclidean"}:
            return score, None
        return score, None

    def _build_query_filter(
        self,
        *,
        tenant_id: str,
        channel: str | None,
        locale: str | None,
        category: str | None,
    ) -> dict[str, Any]:
        query_filter: dict[str, Any] = {"tenant_id": tenant_id}
        if channel is not None:
            query_filter["channel"] = channel
        if locale is not None:
            query_filter["locale"] = locale
        if category is not None:
            query_filter["category"] = category
        return query_filter

    @staticmethod
    def _extract_matches(query_result: object) -> list[Any]:
        if isinstance(query_result, dict):
            matches = query_result.get("matches")
            return list(matches) if isinstance(matches, list) else []
        matches = getattr(query_result, "matches", None)
        if isinstance(matches, list):
            return list(matches)
        model_dump = getattr(query_result, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                matches = dumped.get("matches")
                return list(matches) if isinstance(matches, list) else []
        to_dict = getattr(query_result, "to_dict", None)
        if callable(to_dict):
            dumped = to_dict()
            if isinstance(dumped, dict):
                matches = dumped.get("matches")
                return list(matches) if isinstance(matches, list) else []
        return []

    @staticmethod
    def _extract_match_parts(match: object) -> tuple[dict[str, Any], object]:
        if isinstance(match, dict):
            metadata = match.get("metadata")
            if isinstance(metadata, dict):
                return dict(metadata), match.get("score")
            return {}, match.get("score")
        metadata = getattr(match, "metadata", None)
        score = getattr(match, "score", None)
        if isinstance(metadata, dict):
            return dict(metadata), score
        as_dict = getattr(match, "dict", None)
        if callable(as_dict):
            dumped = as_dict()
            if isinstance(dumped, dict):
                metadata = dumped.get("metadata")
                if isinstance(metadata, dict):
                    return dict(metadata), dumped.get("score")
        return {}, score

    def _normalise_item(
        self,
        *,
        metadata: dict[str, Any],
        score_raw: object,
    ) -> dict[str, Any]:
        missing_keys = sorted(
            key for key in self._required_metadata_keys if key not in metadata
        )
        if missing_keys:
            missing_text = ", ".join(missing_keys)
            raise RuntimeError(
                "Pinecone knowledge gateway metadata is missing required key(s): "
                f"{missing_text}."
            )
        tenant_id = self._normalize_uuid_text(
            metadata.get("tenant_id"),
            field_name="tenant_id",
        )
        revision_id = self._normalize_uuid_text(
            metadata.get("knowledge_entry_revision_id"),
            field_name="knowledge_entry_revision_id",
        )
        version_id = self._normalize_uuid_text(
            metadata.get("knowledge_pack_version_id"),
            field_name="knowledge_pack_version_id",
        )
        similarity, distance = self._normalize_similarity_distance(score_raw)
        title = self._coerce_optional_string(metadata.get("title"))
        body = self._coerce_optional_string(metadata.get("body"))
        return {
            "knowledge_entry_revision_id": revision_id,
            "knowledge_pack_version_id": version_id,
            "tenant_id": tenant_id,
            "channel": self._coerce_optional_string(metadata.get("channel")),
            "locale": self._coerce_optional_string(metadata.get("locale")),
            "category": self._coerce_optional_string(metadata.get("category")),
            "title": title,
            "snippet": self._build_snippet(title=title, body=body),
            "similarity": similarity,
            "distance": distance,
        }

    def _normalise_items(
        self,
        *,
        query_result: object,
        min_similarity: float | None,
    ) -> list[dict[str, Any]]:
        matches = self._extract_matches(query_result)
        items: list[dict[str, Any]] = []
        for match in matches:
            metadata, score = self._extract_match_parts(match)
            item = self._normalise_item(
                metadata=metadata,
                score_raw=score,
            )
            if min_similarity is not None and (
                item["similarity"] is None
                or float(item["similarity"]) < float(min_similarity)
            ):
                continue
            items.append(item)
        return items

    async def _query_index(
        self,
        *,
        query_vector: list[float],
        query_filter: dict[str, Any],
        top_k: int,
    ) -> Any:
        index = await self._get_index()
        query = getattr(index, "query", None)
        if callable(query) is not True:
            raise RuntimeError("Pinecone knowledge gateway query API is unavailable.")

        query_kwargs: dict[str, Any] = {
            "vector": query_vector,
            "top_k": top_k,
            "filter": query_filter,
            "include_metadata": True,
            "include_values": False,
        }
        if self._search_namespace is not None:
            query_kwargs["namespace"] = self._search_namespace

        query_result = await self._await_with_timeout(
            self._call_provider_method(query, **query_kwargs),
            timeout_seconds=self._api_timeout_seconds,
        )
        if not self._extract_matches(query_result):
            if isinstance(query_result, dict):
                if "matches" in query_result and isinstance(
                    query_result.get("matches"),
                    list,
                ):
                    return query_result
            elif hasattr(query_result, "matches"):
                return query_result
            raise RuntimeError(
                "Pinecone knowledge gateway returned an invalid query payload."
            )
        return query_result

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
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if attempt >= attempts:
                    raise
                delay_seconds = float(self._api_retry_backoff_seconds) * (
                    2 ** (attempt - 1)
                )
                self._logging_gateway.warning(
                    "PineconeKnowledgeGateway: transient %s failure; retrying "
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

    def _warn_missing_timeout_in_production(self) -> None:
        environment = str(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "environment", "")
        ).strip().lower()
        if environment != "production":
            return
        if self._api_timeout_seconds is None:
            self._logging_gateway.warning(
                "PineconeKnowledgeGateway: timeout_seconds is not configured in production."
            )

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Pinecone knowledge gateway is closed.")

    async def check_readiness(self) -> None:
        self._assert_open()
        timeout_seconds = self._api_timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 5.0

        index = await self._await_with_timeout(
            self._get_index(),
            timeout_seconds=timeout_seconds,
        )
        describe_index_stats = getattr(index, "describe_index_stats", None)
        if callable(describe_index_stats) is not True:
            raise RuntimeError(
                "Pinecone knowledge gateway readiness probe is unavailable."
            )
        try:
            await self._await_with_timeout(
                self._call_provider_method(describe_index_stats),
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Pinecone knowledge gateway readiness probe failed."
            ) from exc
        try:
            await self._await_with_timeout(
                self._get_encoder(),
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Pinecone knowledge gateway encoder initialization failed."
            ) from exc

    async def search(
        self,
        params: PineconeSearchVendorParams,
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
                request_factory=lambda: self._query_index(
                    query_vector=query_vector,
                    query_filter=query_filter,
                    top_k=top_k,
                ),
            )
            items = self._normalise_items(
                query_result=raw_response,
                min_similarity=min_similarity,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "PineconeKnowledgeGateway transport failure "
                f"(operation=search error={type(exc).__name__}: {exc})"
            )
            raise KnowledgeGatewayRuntimeError(
                provider="pinecone",
                operation="search",
                cause=exc,
            ) from exc

        return KnowledgeSearchResult(
            items=items,
            total_count=None,
            raw_vendor={
                "provider": "pinecone",
                "host": self._api_host,
                "namespace": self._search_namespace,
                "metric": self._search_metric,
                "result_count": len(items),
                "top_k": top_k,
                "min_similarity": min_similarity,
            },
        )

    @staticmethod
    async def _close_resource(resource: object) -> None:
        close = getattr(resource, "close", None)
        if callable(close):
            maybe_awaitable = close()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
            return
        aclose = getattr(resource, "aclose", None)
        if callable(aclose):
            maybe_awaitable = aclose()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

    async def aclose(self) -> None:
        if self._closed:
            return None
        self._closed = True
        if self._index is not None:
            await self._close_resource(self._index)
        if self._client is not None:
            await self._close_resource(self._client)
        self._index = None
        self._client = None
        return None
