"""Provides a knowledge retrieval gateway for ChromaDB HTTP collections."""

__all__ = ["ChromaKnowledgeGateway"]

import asyncio
import inspect
from math import isfinite
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from sentence_transformers import SentenceTransformer

from mugen.core.contract.dto.chromadb.search import ChromaSearchVendorParams
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
class ChromaKnowledgeGateway(IKnowledgeGateway):
    """A knowledge retrieval gateway for ChromaDB HTTP collections."""

    _default_api_port = 8000
    _default_api_ssl = False
    _default_encoder_model = "all-mpnet-base-v2"
    _default_encoder_max_concurrency = 4
    _default_api_max_retries = 0
    _default_api_retry_backoff_seconds = 0.5
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

        self._api_host = self._resolve_api_host()
        self._api_port = self._resolve_api_port()
        self._api_ssl = self._resolve_api_ssl()
        self._api_headers = self._resolve_api_headers()
        self._api_tenant = self._resolve_optional_api_string("tenant")
        self._api_database = self._resolve_optional_api_string("database")
        self._api_timeout_seconds = self._resolve_api_timeout_seconds()
        self._api_max_retries = self._resolve_api_max_retries()
        self._api_retry_backoff_seconds = self._resolve_api_retry_backoff_seconds()

        self._search_collection = self._resolve_search_collection()
        self._search_default_top_k = self._resolve_search_default_top_k()
        self._search_max_top_k = self._resolve_search_max_top_k()
        if self._search_default_top_k > self._search_max_top_k:
            self._logging_gateway.warning(
                "ChromaKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k."
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
        self._collection = None
        self._collection_lock = asyncio.Lock()

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

    @staticmethod
    def _parse_bool(
        value: object,
        *,
        default: bool,
    ) -> bool:
        if isinstance(value, bool):
            return value
        if value in [None, ""]:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    def _resolve_api_host(self) -> str:
        raw_value = getattr(self._section("chromadb", "api"), "host", "")
        if not isinstance(raw_value, str):
            return ""
        return raw_value.strip()

    def _resolve_api_port(self) -> int:
        raw_value = getattr(
            self._section("chromadb", "api"),
            "port",
            self._default_api_port,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="chromadb.api.port",
            default=self._default_api_port,
        )

    def _resolve_api_ssl(self) -> bool:
        raw_value = getattr(
            self._section("chromadb", "api"),
            "ssl",
            self._default_api_ssl,
        )
        return self._parse_bool(
            raw_value,
            default=self._default_api_ssl,
        )

    def _resolve_api_headers(self) -> dict[str, str]:
        raw_value = getattr(self._section("chromadb", "api"), "headers", None)
        if raw_value in [None, ""]:
            return {}
        if not isinstance(raw_value, dict):
            raise RuntimeError(
                "Invalid configuration: chromadb.api.headers must be a table of strings."
            )
        headers: dict[str, str] = {}
        for key, value in raw_value.items():
            if not isinstance(key, str) or key.strip() == "":
                raise RuntimeError(
                    "Invalid configuration: chromadb.api.headers keys must be non-empty strings."
                )
            if not isinstance(value, str):
                raise RuntimeError(
                    "Invalid configuration: chromadb.api.headers values must be strings."
                )
            headers[key.strip()] = value
        return headers

    def _resolve_optional_api_string(self, key: str) -> str | None:
        raw_value = getattr(self._section("chromadb", "api"), key, None)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return normalized

    def _resolve_api_timeout_seconds(self) -> float | None:
        raw_value = getattr(self._section("chromadb", "api"), "timeout_seconds", None)
        return parse_optional_positive_finite_float(
            raw_value,
            "chromadb.api.timeout_seconds",
        )

    def _resolve_api_max_retries(self) -> int:
        raw_value = getattr(
            self._section("chromadb", "api"),
            "max_retries",
            self._default_api_max_retries,
        )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            self._logging_gateway.warning(
                "ChromaKnowledgeGateway: Invalid max_retries configuration."
            )
            return self._default_api_max_retries
        if parsed < 0:
            self._logging_gateway.warning(
                "ChromaKnowledgeGateway: max_retries must be non-negative."
            )
            return self._default_api_max_retries
        return parsed

    def _resolve_api_retry_backoff_seconds(self) -> float:
        raw_value = getattr(
            self._section("chromadb", "api"),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_value,
            field_name="chromadb.api.retry_backoff_seconds",
            default=self._default_api_retry_backoff_seconds,
        )

    def _resolve_search_collection(self) -> str:
        raw_value = getattr(self._section("chromadb", "search"), "collection", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError(
                "Invalid configuration: chromadb.search.collection is required."
            )
        return raw_value.strip()

    def _resolve_search_default_top_k(self) -> int:
        raw_value = getattr(
            self._section("chromadb", "search"),
            "default_top_k",
            self._default_search_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="chromadb.search.default_top_k",
            default=self._default_search_top_k,
        )

    def _resolve_search_max_top_k(self) -> int:
        raw_value = getattr(
            self._section("chromadb", "search"),
            "max_top_k",
            self._default_search_max_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="chromadb.search.max_top_k",
            default=self._default_search_max_top_k,
        )

    def _resolve_snippet_max_chars(self) -> int:
        raw_value = getattr(
            self._section("chromadb", "search"),
            "snippet_max_chars",
            self._default_snippet_max_chars,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="chromadb.search.snippet_max_chars",
            default=self._default_snippet_max_chars,
        )

    def _resolve_encoder_model_name(self) -> str:
        raw_value = getattr(
            self._section("chromadb", "encoder"),
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
            self._section("chromadb", "encoder"),
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
    def _create_http_client(**kwargs):
        from chromadb import HttpClient  # pylint: disable=import-outside-toplevel

        return HttpClient(**kwargs)

    def _build_client(self):
        if self._api_host == "":
            raise RuntimeError("Chroma knowledge gateway requires chromadb.api.host.")
        kwargs: dict[str, Any] = {
            "host": self._api_host,
            "port": self._api_port,
            "ssl": self._api_ssl,
        }
        if self._api_headers:
            kwargs["headers"] = dict(self._api_headers)
        if self._api_tenant is not None:
            kwargs["tenant"] = self._api_tenant
        if self._api_database is not None:
            kwargs["database"] = self._api_database
        return self._create_http_client(**kwargs)

    async def _get_client(self):
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._build_client)
            return self._client

    async def _get_collection(self):
        if self._collection is not None:
            return self._collection
        async with self._collection_lock:
            if self._collection is None:
                client = await self._get_client()
                self._collection = await asyncio.to_thread(
                    client.get_collection,
                    self._search_collection,
                )
            return self._collection

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
    def _coerce_float(value: object) -> float | None:
        if value in [None, ""]:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_optional_string(value: object) -> str | None:
        if value in [None, ""]:
            return None
        if isinstance(value, str):
            return value
        return str(value)

    def _build_snippet(self, *, title: str | None, body: str | None) -> str | None:
        source = body if body not in [None, ""] else title
        if source in [None, ""]:
            return None
        text = str(source)
        if len(text) <= self._snippet_max_chars:
            return text
        return text[: self._snippet_max_chars]

    @staticmethod
    def _normalize_uuid_text(value: object, *, field_name: str) -> str:
        if isinstance(value, uuid.UUID):
            return str(value)
        if not isinstance(value, str):
            raise RuntimeError(
                f"Chroma knowledge gateway metadata field '{field_name}' must be a UUID string."
            )
        normalized = value.strip()
        if normalized == "":
            raise RuntimeError(
                f"Chroma knowledge gateway metadata field '{field_name}' must be a UUID string."
            )
        try:
            parsed = uuid.UUID(normalized)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError(
                f"Chroma knowledge gateway metadata field '{field_name}' must be a UUID string."
            ) from exc
        return str(parsed)

    @staticmethod
    def _extract_nested_list(value: object) -> list[Any]:
        if not isinstance(value, list):
            return []
        if not value:
            return []
        first = value[0]
        if isinstance(first, list):
            return list(first)
        return list(value)

    def _normalise_item(
        self,
        *,
        metadata: object,
        document: object,
        distance_raw: object,
    ) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            raise RuntimeError(
                "Chroma knowledge gateway metadata item must be a table."
            )
        missing_keys = sorted(
            key for key in self._required_metadata_keys if key not in metadata
        )
        if missing_keys:
            missing_text = ", ".join(missing_keys)
            raise RuntimeError(
                "Chroma knowledge gateway metadata is missing required key(s): "
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
        title = self._coerce_optional_string(metadata.get("title"))
        body = self._coerce_optional_string(metadata.get("body"))
        if body in [None, ""]:
            body = self._coerce_optional_string(document)
        distance = self._coerce_float(distance_raw)
        similarity = None if distance is None else float(1.0 - distance)
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
        query_result: dict[str, Any],
        min_similarity: float | None,
    ) -> list[dict[str, Any]]:
        metadatas = self._extract_nested_list(query_result.get("metadatas"))
        documents = self._extract_nested_list(query_result.get("documents"))
        distances = self._extract_nested_list(query_result.get("distances"))
        items: list[dict[str, Any]] = []
        for index, metadata in enumerate(metadatas):
            item = self._normalise_item(
                metadata=metadata,
                document=documents[index] if index < len(documents) else None,
                distance_raw=distances[index] if index < len(distances) else None,
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
        tenant_id: str,
        channel: str | None,
        locale: str | None,
        category: str | None,
        top_k: int,
    ) -> dict[str, Any]:
        collection = await self._get_collection()
        where: dict[str, Any] = {"tenant_id": tenant_id}
        if channel is not None:
            where["channel"] = channel
        if locale is not None:
            where["locale"] = locale
        if category is not None:
            where["category"] = category
        query_result = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where,
            include=["metadatas", "documents", "distances"],
        )
        if not isinstance(query_result, dict):
            raise RuntimeError(
                "Chroma knowledge gateway returned an invalid query payload."
            )
        return dict(query_result)

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
                    "ChromaKnowledgeGateway: transient %s failure; retrying "
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

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Chroma knowledge gateway is closed.")

    async def check_readiness(self) -> None:
        self._assert_open()
        if self._api_host == "":
            raise RuntimeError("Chroma knowledge gateway requires chromadb.api.host.")
        if self._search_collection.strip() == "":
            raise RuntimeError(
                "Chroma knowledge gateway requires chromadb.search.collection."
            )
        timeout_seconds = self._api_timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 5.0
        try:
            await asyncio.wait_for(self._get_collection(), timeout=timeout_seconds)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Chroma knowledge gateway collection readiness probe failed."
            ) from exc
        try:
            await asyncio.wait_for(self._get_encoder(), timeout=timeout_seconds)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Chroma knowledge gateway encoder initialization failed."
            ) from exc

    async def search(
        self,
        params: ChromaSearchVendorParams,
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

        try:
            raw_response = await self._execute_with_retry(
                operation="search",
                request_factory=lambda: self._query_collection(
                    query_vector=query_vector,
                    tenant_id=tenant_id,
                    channel=channel,
                    locale=locale,
                    category=category,
                    top_k=top_k,
                ),
            )
            items = self._normalise_items(
                query_result=raw_response,
                min_similarity=min_similarity,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "ChromaKnowledgeGateway transport failure "
                f"(operation=search error={type(exc).__name__}: {exc})"
            )
            raise KnowledgeGatewayRuntimeError(
                provider="chromadb",
                operation="search",
                cause=exc,
            ) from exc

        return KnowledgeSearchResult(
            items=items,
            total_count=None,
            raw_vendor={
                "provider": "chromadb",
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
        self._collection = None
        self._client = None
        return None
