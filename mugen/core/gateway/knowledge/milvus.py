"""Provides a knowledge retrieval gateway for Milvus vector collections."""

__all__ = ["MilvusKnowledgeGateway"]

import asyncio
import inspect
from math import isfinite
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from sentence_transformers import SentenceTransformer

from mugen.core.contract.dto.milvus.search import MilvusSearchVendorParams
from mugen.core.contract.gateway.knowledge import (
    IKnowledgeGateway,
    KnowledgeGatewayRuntimeError,
    KnowledgeSearchResult,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.utility.config_value import (
    parse_nonnegative_finite_float,
    parse_optional_positive_finite_float,
)


# pylint: disable=too-many-instance-attributes
class MilvusKnowledgeGateway(IKnowledgeGateway):
    """A knowledge retrieval gateway for Milvus vector collections."""

    _default_encoder_model = "all-mpnet-base-v2"
    _default_encoder_max_concurrency = 4
    _default_api_max_retries = 0
    _default_api_retry_backoff_seconds = 0.5
    _default_search_top_k = 10
    _default_search_max_top_k = 50
    _default_snippet_max_chars = 240
    _default_search_vector_field = "embedding"
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

        self._api_uri = self._resolve_api_uri()
        self._api_token = self._resolve_optional_api_string("token")
        self._api_timeout_seconds = self._resolve_api_timeout_seconds()
        self._api_max_retries = self._resolve_api_max_retries()
        self._api_retry_backoff_seconds = self._resolve_api_retry_backoff_seconds()

        self._search_collection = self._resolve_search_collection()
        self._search_vector_field = self._resolve_search_vector_field()
        self._search_default_top_k = self._resolve_search_default_top_k()
        self._search_max_top_k = self._resolve_search_max_top_k()
        if self._search_default_top_k > self._search_max_top_k:
            self._logging_gateway.warning(
                "MilvusKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k."
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

    def _resolve_api_uri(self) -> str:
        raw_value = getattr(self._section("milvus", "api"), "uri", "")
        if not isinstance(raw_value, str):
            return ""
        return raw_value.strip()

    def _resolve_optional_api_string(self, key: str) -> str | None:
        raw_value = getattr(self._section("milvus", "api"), key, None)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return normalized

    def _resolve_api_timeout_seconds(self) -> float | None:
        raw_value = getattr(self._section("milvus", "api"), "timeout_seconds", None)
        return parse_optional_positive_finite_float(
            raw_value,
            "milvus.api.timeout_seconds",
        )

    def _resolve_api_max_retries(self) -> int:
        raw_value = getattr(
            self._section("milvus", "api"),
            "max_retries",
            self._default_api_max_retries,
        )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            self._logging_gateway.warning(
                "MilvusKnowledgeGateway: Invalid max_retries configuration."
            )
            return self._default_api_max_retries
        if parsed < 0:
            self._logging_gateway.warning(
                "MilvusKnowledgeGateway: max_retries must be non-negative."
            )
            return self._default_api_max_retries
        return parsed

    def _resolve_api_retry_backoff_seconds(self) -> float:
        raw_value = getattr(
            self._section("milvus", "api"),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_value,
            field_name="milvus.api.retry_backoff_seconds",
            default=self._default_api_retry_backoff_seconds,
        )

    def _resolve_search_collection(self) -> str:
        raw_value = getattr(self._section("milvus", "search"), "collection", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError(
                "Invalid configuration: milvus.search.collection is required."
            )
        return raw_value.strip()

    def _resolve_search_vector_field(self) -> str:
        raw_value = getattr(
            self._section("milvus", "search"),
            "vector_field",
            self._default_search_vector_field,
        )
        if not isinstance(raw_value, str):
            return self._default_search_vector_field
        normalized = raw_value.strip()
        if normalized == "":
            raise RuntimeError(
                "Invalid configuration: milvus.search.vector_field must be non-empty."
            )
        return normalized

    def _resolve_search_default_top_k(self) -> int:
        raw_value = getattr(
            self._section("milvus", "search"),
            "default_top_k",
            self._default_search_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="milvus.search.default_top_k",
            default=self._default_search_top_k,
        )

    def _resolve_search_max_top_k(self) -> int:
        raw_value = getattr(
            self._section("milvus", "search"),
            "max_top_k",
            self._default_search_max_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="milvus.search.max_top_k",
            default=self._default_search_max_top_k,
        )

    def _resolve_snippet_max_chars(self) -> int:
        raw_value = getattr(
            self._section("milvus", "search"),
            "snippet_max_chars",
            self._default_snippet_max_chars,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="milvus.search.snippet_max_chars",
            default=self._default_snippet_max_chars,
        )

    def _resolve_encoder_model_name(self) -> str:
        raw_value = getattr(
            self._section("milvus", "encoder"),
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
            self._section("milvus", "encoder"),
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
    def _create_client(**kwargs):
        from pymilvus import MilvusClient  # pylint: disable=import-outside-toplevel

        return MilvusClient(**kwargs)

    def _build_client(self):
        if self._api_uri == "":
            raise RuntimeError("Milvus knowledge gateway requires milvus.api.uri.")
        kwargs: dict[str, Any] = {
            "uri": self._api_uri,
        }
        if self._api_token is not None:
            kwargs["token"] = self._api_token
        if self._api_timeout_seconds is not None:
            kwargs["timeout"] = float(self._api_timeout_seconds)
        return self._create_client(**kwargs)

    async def _get_client(self):
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._build_client)
            return self._client

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
                f"Milvus knowledge gateway payload field '{field_name}' must be a UUID string."
            )
        normalized = value.strip()
        if normalized == "":
            raise RuntimeError(
                f"Milvus knowledge gateway payload field '{field_name}' must be a UUID string."
            )
        try:
            parsed = uuid.UUID(normalized)
        except (TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError(
                f"Milvus knowledge gateway payload field '{field_name}' must be a UUID string."
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

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _build_filter_expression(
        self,
        *,
        tenant_id: str,
        channel: str | None,
        locale: str | None,
        category: str | None,
    ) -> str:
        conditions = [
            f'tenant_id == "{self._escape_filter_value(tenant_id)}"',
        ]
        if channel is not None:
            conditions.append(f'channel == "{self._escape_filter_value(channel)}"')
        if locale is not None:
            conditions.append(f'locale == "{self._escape_filter_value(locale)}"')
        if category is not None:
            conditions.append(f'category == "{self._escape_filter_value(category)}"')
        return " and ".join(conditions)

    @staticmethod
    def _extract_hits(search_result: object) -> list[Any]:
        if not isinstance(search_result, list):
            return []
        if not search_result:
            return []
        first = search_result[0]
        if isinstance(first, list):
            return list(first)
        return list(search_result)

    @staticmethod
    def _extract_hit_payload(hit: object) -> tuple[dict[str, Any], object, object]:
        if isinstance(hit, dict):
            payload = hit.get("entity")
            if isinstance(payload, dict):
                return dict(payload), hit.get("score"), hit.get("distance")
            return dict(hit), hit.get("score"), hit.get("distance")
        payload = getattr(hit, "entity", None)
        if isinstance(payload, dict):
            return (
                dict(payload),
                getattr(hit, "score", None),
                getattr(hit, "distance", None),
            )
        raise RuntimeError("Milvus knowledge gateway hit payload is invalid.")

    def _normalise_item(
        self,
        *,
        payload: dict[str, Any],
        score_raw: object,
        distance_raw: object,
    ) -> dict[str, Any]:
        missing_keys = sorted(
            key for key in self._required_payload_keys if key not in payload
        )
        if missing_keys:
            missing_text = ", ".join(missing_keys)
            raise RuntimeError(
                "Milvus knowledge gateway payload is missing required key(s): "
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
        score = self._coerce_float(score_raw)
        distance = self._coerce_float(distance_raw)
        similarity = score
        if similarity is None and distance is not None:
            similarity = float(1.0 - distance)
        if distance is None and similarity is not None:
            distance = float(1.0 - similarity)
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
            "distance": distance,
        }

    def _normalise_items(
        self,
        *,
        search_result: list[Any],
        min_similarity: float | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for hit in self._extract_hits(search_result):
            payload, score_raw, distance_raw = self._extract_hit_payload(hit)
            item = self._normalise_item(
                payload=payload,
                score_raw=score_raw,
                distance_raw=distance_raw,
            )
            if min_similarity is not None and (
                item["similarity"] is None
                or float(item["similarity"]) < float(min_similarity)
            ):
                continue
            items.append(item)
        return items

    async def _query_collection(
        self,
        *,
        query_vector: list[float],
        filter_expression: str,
        top_k: int,
    ) -> list[Any]:
        client = await self._get_client()
        search = getattr(client, "search", None)
        if callable(search) is not True:
            raise RuntimeError("Milvus knowledge gateway search API is unavailable.")
        search_result = await asyncio.to_thread(
            search,
            collection_name=self._search_collection,
            data=[query_vector],
            anns_field=self._search_vector_field,
            limit=top_k,
            filter=filter_expression,
            output_fields=list(self._required_payload_keys),
        )
        if not isinstance(search_result, list):
            raise RuntimeError(
                "Milvus knowledge gateway returned an invalid search payload."
            )
        return list(search_result)

    async def _execute_with_retry(
        self,
        *,
        operation: str,
        request_factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        attempts = max(0, int(self._api_max_retries)) + 1
        attempt = 1
        while True:
            try:
                return await request_factory()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if attempt >= attempts:
                    raise
                delay_seconds = float(self._api_retry_backoff_seconds) * (
                    2 ** (attempt - 1)
                )
                self._logging_gateway.warning(
                    "MilvusKnowledgeGateway: transient %s failure; retrying "
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
                attempt += 1

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Milvus knowledge gateway is closed.")

    async def check_readiness(self) -> None:
        self._assert_open()
        if self._api_uri == "":
            raise RuntimeError("Milvus knowledge gateway requires milvus.api.uri.")
        timeout_seconds = self._api_timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 5.0
        client = await asyncio.wait_for(self._get_client(), timeout=timeout_seconds)
        list_collections = getattr(client, "list_collections", None)
        if callable(list_collections) is not True:
            raise RuntimeError(
                "Milvus knowledge gateway readiness probe is unavailable."
            )
        try:
            collections = await asyncio.wait_for(
                asyncio.to_thread(list_collections),
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Milvus knowledge gateway collection readiness probe failed."
            ) from exc
        if not isinstance(collections, list):
            raise RuntimeError(
                "Milvus knowledge gateway readiness probe returned an invalid payload."
            )
        collection_names = {
            str(item).strip() for item in collections if str(item).strip() != ""
        }
        if self._search_collection not in collection_names:
            raise RuntimeError(
                "Milvus knowledge gateway configured collection was not found."
            )
        try:
            await asyncio.wait_for(self._get_encoder(), timeout=timeout_seconds)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Milvus knowledge gateway encoder initialization failed."
            ) from exc

    async def search(
        self,
        params: MilvusSearchVendorParams,
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
        filter_expression = self._build_filter_expression(
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
                    filter_expression=filter_expression,
                    top_k=top_k,
                ),
            )
            items = self._normalise_items(
                search_result=raw_response,
                min_similarity=min_similarity,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "MilvusKnowledgeGateway transport failure "
                f"(operation=search error={type(exc).__name__}: {exc})"
            )
            raise KnowledgeGatewayRuntimeError(
                provider="milvus",
                operation="search",
                cause=exc,
            ) from exc

        return KnowledgeSearchResult(
            items=items,
            total_count=None,
            raw_vendor={
                "provider": "milvus",
                "collection": self._search_collection,
                "vector_field": self._search_vector_field,
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
