"""Provides a knowledge retrieval gateway for Weaviate vector collections."""

__all__ = ["WeaviateKnowledgeGateway"]

import asyncio
import inspect
from math import isfinite
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from sentence_transformers import SentenceTransformer

from mugen.core.contract.dto.weaviate.search import WeaviateSearchVendorParams
from mugen.core.contract.gateway.knowledge import (
    IKnowledgeGateway,
    KnowledgeGatewayRuntimeError,
    KnowledgeSearchResult,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.utility.config_value import (
    parse_bool_flag,
    parse_nonnegative_finite_float,
    parse_optional_positive_finite_float,
)


# pylint: disable=too-many-instance-attributes
class WeaviateKnowledgeGateway(IKnowledgeGateway):
    """A knowledge retrieval gateway for Weaviate vector collections."""

    _default_api_http_port = 8080
    _default_api_http_secure = False
    _default_api_grpc_port = 50051
    _default_api_grpc_secure = False
    _default_encoder_model = "all-mpnet-base-v2"
    _default_encoder_max_concurrency = 4
    _default_api_max_retries = 0
    _default_api_retry_backoff_seconds = 0.5
    _default_search_top_k = 10
    _default_search_max_top_k = 50
    _default_snippet_max_chars = 240
    _required_properties = (
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

        self._api_http_host = self._resolve_api_http_host()
        self._api_http_port = self._resolve_api_http_port()
        self._api_http_secure = self._resolve_api_http_secure()
        self._api_grpc_host = self._resolve_api_grpc_host()
        self._api_grpc_port = self._resolve_api_grpc_port()
        self._api_grpc_secure = self._resolve_api_grpc_secure()
        self._api_key = self._resolve_api_key()
        self._api_headers = self._resolve_api_headers()
        self._api_timeout_seconds = self._resolve_api_timeout_seconds()
        self._api_max_retries = self._resolve_api_max_retries()
        self._api_retry_backoff_seconds = self._resolve_api_retry_backoff_seconds()

        self._search_collection = self._resolve_search_collection()
        self._search_target_vector = self._resolve_search_target_vector()
        self._search_default_top_k = self._resolve_search_default_top_k()
        self._search_max_top_k = self._resolve_search_max_top_k()
        if self._search_default_top_k > self._search_max_top_k:
            self._logging_gateway.warning(
                "WeaviateKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k."
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

    def _resolve_api_http_host(self) -> str:
        raw_value = getattr(self._section("weaviate", "api"), "http_host", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError("Invalid configuration: weaviate.api.http_host is required.")
        return raw_value.strip()

    def _resolve_api_http_port(self) -> int:
        raw_value = getattr(
            self._section("weaviate", "api"),
            "http_port",
            self._default_api_http_port,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="weaviate.api.http_port",
            default=self._default_api_http_port,
        )

    def _resolve_api_http_secure(self) -> bool:
        raw_value = getattr(
            self._section("weaviate", "api"),
            "http_secure",
            self._default_api_http_secure,
        )
        return parse_bool_flag(
            raw_value,
            default=self._default_api_http_secure,
        )

    def _resolve_api_grpc_host(self) -> str:
        raw_value = getattr(self._section("weaviate", "api"), "grpc_host", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError("Invalid configuration: weaviate.api.grpc_host is required.")
        return raw_value.strip()

    def _resolve_api_grpc_port(self) -> int:
        raw_value = getattr(
            self._section("weaviate", "api"),
            "grpc_port",
            self._default_api_grpc_port,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="weaviate.api.grpc_port",
            default=self._default_api_grpc_port,
        )

    def _resolve_api_grpc_secure(self) -> bool:
        raw_value = getattr(
            self._section("weaviate", "api"),
            "grpc_secure",
            self._default_api_grpc_secure,
        )
        return parse_bool_flag(
            raw_value,
            default=self._default_api_grpc_secure,
        )

    def _resolve_api_key(self) -> str | None:
        raw_value = getattr(self._section("weaviate", "api"), "key", None)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return normalized

    def _resolve_api_headers(self) -> dict[str, str]:
        raw_value = getattr(self._section("weaviate", "api"), "headers", None)
        if raw_value in [None, ""]:
            return {}
        if not isinstance(raw_value, dict):
            raise RuntimeError(
                "Invalid configuration: weaviate.api.headers must be a table of strings."
            )
        headers: dict[str, str] = {}
        for key, value in raw_value.items():
            if not isinstance(key, str) or key.strip() == "":
                raise RuntimeError(
                    "Invalid configuration: weaviate.api.headers keys must be non-empty strings."
                )
            if not isinstance(value, str):
                raise RuntimeError(
                    "Invalid configuration: weaviate.api.headers values must be strings."
                )
            headers[key.strip()] = value
        return headers

    def _resolve_api_timeout_seconds(self) -> float | None:
        raw_value = getattr(self._section("weaviate", "api"), "timeout_seconds", None)
        return parse_optional_positive_finite_float(
            raw_value,
            "weaviate.api.timeout_seconds",
        )

    def _resolve_api_max_retries(self) -> int:
        raw_value = getattr(
            self._section("weaviate", "api"),
            "max_retries",
            self._default_api_max_retries,
        )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            self._logging_gateway.warning(
                "WeaviateKnowledgeGateway: Invalid max_retries configuration."
            )
            return self._default_api_max_retries
        if parsed < 0:
            self._logging_gateway.warning(
                "WeaviateKnowledgeGateway: max_retries must be non-negative."
            )
            return self._default_api_max_retries
        return parsed

    def _resolve_api_retry_backoff_seconds(self) -> float:
        raw_value = getattr(
            self._section("weaviate", "api"),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_value,
            field_name="weaviate.api.retry_backoff_seconds",
            default=self._default_api_retry_backoff_seconds,
        )

    def _resolve_search_collection(self) -> str:
        raw_value = getattr(self._section("weaviate", "search"), "collection", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError(
                "Invalid configuration: weaviate.search.collection is required."
            )
        return raw_value.strip()

    def _resolve_search_target_vector(self) -> str | None:
        raw_value = getattr(
            self._section("weaviate", "search"),
            "target_vector",
            None,
        )
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return normalized

    def _resolve_search_default_top_k(self) -> int:
        raw_value = getattr(
            self._section("weaviate", "search"),
            "default_top_k",
            self._default_search_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="weaviate.search.default_top_k",
            default=self._default_search_top_k,
        )

    def _resolve_search_max_top_k(self) -> int:
        raw_value = getattr(
            self._section("weaviate", "search"),
            "max_top_k",
            self._default_search_max_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="weaviate.search.max_top_k",
            default=self._default_search_max_top_k,
        )

    def _resolve_snippet_max_chars(self) -> int:
        raw_value = getattr(
            self._section("weaviate", "search"),
            "snippet_max_chars",
            self._default_snippet_max_chars,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="weaviate.search.snippet_max_chars",
            default=self._default_snippet_max_chars,
        )

    def _resolve_encoder_model_name(self) -> str:
        raw_value = getattr(
            self._section("weaviate", "encoder"),
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
            self._section("weaviate", "encoder"),
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
    def _create_client(
        *,
        http_host: str,
        http_port: int,
        http_secure: bool,
        grpc_host: str,
        grpc_port: int,
        grpc_secure: bool,
        api_key: str | None,
        headers: dict[str, str],
        timeout_seconds: float | None,
    ):
        # pylint: disable=import-outside-toplevel
        from weaviate import connect_to_custom
        from weaviate.auth import Auth
        from weaviate.classes.init import AdditionalConfig, Timeout

        additional_config = None
        if timeout_seconds is not None:
            timeout = Timeout(
                query=float(timeout_seconds),
                init=float(timeout_seconds),
            )
            additional_config = AdditionalConfig(timeout=timeout)

        auth_credentials = None
        if api_key is not None:
            auth_credentials = Auth.api_key(api_key)

        return connect_to_custom(
            http_host=http_host,
            http_port=http_port,
            http_secure=http_secure,
            grpc_host=grpc_host,
            grpc_port=grpc_port,
            grpc_secure=grpc_secure,
            headers=dict(headers) if headers else None,
            additional_config=additional_config,
            auth_credentials=auth_credentials,
            skip_init_checks=False,
        )

    def _build_client(self):
        if self._api_http_host == "":
            raise RuntimeError(
                "Weaviate knowledge gateway requires weaviate.api.http_host."
            )
        if self._api_grpc_host == "":
            raise RuntimeError(
                "Weaviate knowledge gateway requires weaviate.api.grpc_host."
            )
        return self._create_client(
            http_host=self._api_http_host,
            http_port=self._api_http_port,
            http_secure=self._api_http_secure,
            grpc_host=self._api_grpc_host,
            grpc_port=self._api_grpc_port,
            grpc_secure=self._api_grpc_secure,
            api_key=self._api_key,
            headers=self._api_headers,
            timeout_seconds=self._api_timeout_seconds,
        )

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
                collections = getattr(client, "collections", None)
                get_collection = getattr(collections, "get", None)
                if callable(get_collection) is not True:
                    raise RuntimeError(
                        "Weaviate knowledge gateway collection API is unavailable."
                    )
                self._collection = await asyncio.to_thread(
                    get_collection,
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
    def _normalize_uuid_text(value: object, *, field_name: str) -> str:
        if isinstance(value, uuid.UUID):
            return str(value)
        if not isinstance(value, str):
            raise RuntimeError(
                "Weaviate knowledge gateway property "
                f"'{field_name}' must be a UUID string."
            )
        normalized = value.strip()
        if normalized == "":
            raise RuntimeError(
                "Weaviate knowledge gateway property "
                f"'{field_name}' must be a UUID string."
            )
        try:
            parsed = uuid.UUID(normalized)
        except (TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError(
                "Weaviate knowledge gateway property "
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

    @staticmethod
    def _metadata_query_factory():
        # pylint: disable=import-outside-toplevel
        from weaviate.classes.query import MetadataQuery

        return MetadataQuery(distance=True)

    @staticmethod
    def _build_query_filters(
        *,
        tenant_id: str,
        channel: str | None,
        locale: str | None,
        category: str | None,
    ):
        # pylint: disable=import-outside-toplevel
        from weaviate.classes.query import Filter

        filters = [Filter.by_property("tenant_id").equal(tenant_id)]
        if channel is not None:
            filters.append(Filter.by_property("channel").equal(channel))
        if locale is not None:
            filters.append(Filter.by_property("locale").equal(locale))
        if category is not None:
            filters.append(Filter.by_property("category").equal(category))
        if len(filters) == 1:
            return filters[0]
        return Filter.all_of(filters)

    @staticmethod
    def _extract_query_objects(query_result: object) -> list[Any]:
        if isinstance(query_result, list):
            return list(query_result)
        if isinstance(query_result, dict):
            objects = query_result.get("objects")
            if isinstance(objects, list):
                return list(objects)
            raise RuntimeError(
                "Weaviate knowledge gateway returned an invalid query payload."
            )
        objects = getattr(query_result, "objects", None)
        if isinstance(objects, list):
            return list(objects)
        raise RuntimeError("Weaviate knowledge gateway returned an invalid query payload.")

    @staticmethod
    def _extract_properties(item: object) -> dict[str, Any]:
        if isinstance(item, dict):
            properties = item.get("properties")
            if isinstance(properties, dict):
                return dict(properties)
            return dict(item)
        properties = getattr(item, "properties", None)
        if isinstance(properties, dict):
            return dict(properties)
        model_dump = getattr(properties, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        as_dict = getattr(properties, "dict", None)
        if callable(as_dict):
            dumped = as_dict()
            if isinstance(dumped, dict):
                return dumped
        if hasattr(properties, "__dict__"):
            return dict(getattr(properties, "__dict__", {}))
        return {}

    def _extract_distance(self, item: object) -> float | None:
        distance_raw = None
        if isinstance(item, dict):
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                distance_raw = metadata.get("distance")
            else:
                distance_raw = item.get("distance")
        else:
            metadata = getattr(item, "metadata", None)
            if isinstance(metadata, dict):
                distance_raw = metadata.get("distance")
            elif metadata is not None:
                distance_raw = getattr(metadata, "distance", None)
            if distance_raw in [None, ""]:
                distance_raw = getattr(item, "distance", None)
        return self._coerce_float(distance_raw)

    def _normalise_item(
        self,
        *,
        item: object,
    ) -> dict[str, Any]:
        properties = self._extract_properties(item)
        missing_keys = sorted(
            key for key in self._required_properties if key not in properties
        )
        if missing_keys:
            missing_text = ", ".join(missing_keys)
            raise RuntimeError(
                "Weaviate knowledge gateway object is missing required property key(s): "
                f"{missing_text}."
            )
        tenant_id = self._normalize_uuid_text(
            properties.get("tenant_id"),
            field_name="tenant_id",
        )
        revision_id = self._normalize_uuid_text(
            properties.get("knowledge_entry_revision_id"),
            field_name="knowledge_entry_revision_id",
        )
        version_id = self._normalize_uuid_text(
            properties.get("knowledge_pack_version_id"),
            field_name="knowledge_pack_version_id",
        )
        title = self._coerce_optional_string(properties.get("title"))
        body = self._coerce_optional_string(properties.get("body"))
        distance = self._extract_distance(item)
        similarity = None if distance is None else float(1.0 - distance)
        return {
            "knowledge_entry_revision_id": revision_id,
            "knowledge_pack_version_id": version_id,
            "tenant_id": tenant_id,
            "channel": self._coerce_optional_string(properties.get("channel")),
            "locale": self._coerce_optional_string(properties.get("locale")),
            "category": self._coerce_optional_string(properties.get("category")),
            "title": title,
            "snippet": self._build_snippet(
                title=title,
                body=body,
            ),
            "similarity": similarity,
            "distance": distance,
        }

    def _normalise_items(
        self,
        *,
        query_result: object,
        min_similarity: float | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for object_item in self._extract_query_objects(query_result):
            item = self._normalise_item(item=object_item)
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
        query_filters: object,
        top_k: int,
    ) -> object:
        collection = await self._get_collection()
        query = getattr(getattr(collection, "query", None), "near_vector", None)
        if callable(query) is not True:
            raise RuntimeError("Weaviate knowledge gateway query API is unavailable.")

        query_kwargs: dict[str, Any] = {
            "near_vector": query_vector,
            "limit": top_k,
            "filters": query_filters,
            "return_metadata": self._metadata_query_factory(),
            "return_properties": list(self._required_properties),
        }
        if self._search_target_vector is not None:
            query_kwargs["target_vector"] = self._search_target_vector
        query_result = await asyncio.to_thread(query, **query_kwargs)
        self._extract_query_objects(query_result)
        return query_result

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
                    "WeaviateKnowledgeGateway: transient %s failure; retrying "
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
            raise RuntimeError("Weaviate knowledge gateway is closed.")

    async def check_readiness(self) -> None:
        self._assert_open()
        timeout_seconds = self._api_timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 5.0
        client = await asyncio.wait_for(self._get_client(), timeout=timeout_seconds)

        is_ready = getattr(client, "is_ready", None)
        if callable(is_ready) is not True:
            raise RuntimeError(
                "Weaviate knowledge gateway readiness probe is unavailable."
            )
        ready = await asyncio.wait_for(
            asyncio.to_thread(is_ready),
            timeout=timeout_seconds,
        )
        if ready is not True:
            raise RuntimeError("Weaviate knowledge gateway readiness probe failed.")

        exists = getattr(getattr(client, "collections", None), "exists", None)
        if callable(exists) is not True:
            raise RuntimeError(
                "Weaviate knowledge gateway collection probe is unavailable."
            )
        collection_exists = await asyncio.wait_for(
            asyncio.to_thread(exists, self._search_collection),
            timeout=timeout_seconds,
        )
        if bool(collection_exists) is not True:
            raise RuntimeError(
                "Weaviate knowledge gateway configured collection was not found."
            )

        try:
            await asyncio.wait_for(self._get_encoder(), timeout=timeout_seconds)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Weaviate knowledge gateway encoder initialization failed."
            ) from exc

    async def search(
        self,
        params: WeaviateSearchVendorParams,
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
        query_filters = self._build_query_filters(
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
                    query_filters=query_filters,
                    top_k=top_k,
                ),
            )
            items = self._normalise_items(
                query_result=raw_response,
                min_similarity=min_similarity,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "WeaviateKnowledgeGateway transport failure "
                f"(operation=search error={type(exc).__name__}: {exc})"
            )
            raise KnowledgeGatewayRuntimeError(
                provider="weaviate",
                operation="search",
                cause=exc,
            ) from exc

        return KnowledgeSearchResult(
            items=items,
            total_count=None,
            raw_vendor={
                "provider": "weaviate",
                "collection": self._search_collection,
                "target_vector": self._search_target_vector,
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
