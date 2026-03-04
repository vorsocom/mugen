"""Provides a knowledge retrieval gateway for pgvector-backed Postgres tables."""

__all__ = ["PgVectorKnowledgeGateway"]

import asyncio
from math import isfinite
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from sentence_transformers import SentenceTransformer
from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.dto.pgvector.search import PgVectorSearchVendorParams
from mugen.core.contract.gateway.knowledge import (
    IKnowledgeGateway,
    KnowledgeGatewayRuntimeError,
    KnowledgeSearchResult,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.storage.rdbms.sqla.shared_runtime import SharedSQLAlchemyRuntime
from mugen.core.utility.config_value import (
    parse_nonnegative_finite_float,
    parse_optional_positive_finite_float,
)
from mugen.core.utility.rdbms_schema import (
    qualify_sql_name,
    resolve_core_rdbms_schema,
    validate_sql_identifier,
)


# pylint: disable=too-many-instance-attributes
class PgVectorKnowledgeGateway(IKnowledgeGateway):
    """A knowledge retrieval gateway for pgvector-backed Postgres tables."""

    _default_encoder_model = "all-mpnet-base-v2"
    _default_encoder_max_concurrency = 4
    _default_api_max_retries = 0
    _default_api_retry_backoff_seconds = 0.5
    _default_search_metric = "cosine"
    _default_search_top_k = 10
    _default_search_max_top_k = 50
    _default_snippet_max_chars = 240
    _required_projection_columns = {
        "tenant_id",
        "knowledge_entry_revision_id",
        "knowledge_pack_version_id",
        "channel",
        "locale",
        "category",
        "title",
        "body",
        "embedding",
    }

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._runtime = SharedSQLAlchemyRuntime.from_config(self._config)
        self._engine = self._runtime.engine
        self._closed = False

        self._search_schema = self._resolve_search_schema()
        self._search_table = self._resolve_search_table()
        self._search_metric = self._resolve_search_metric()
        self._search_default_top_k = self._resolve_search_default_top_k()
        self._search_max_top_k = self._resolve_search_max_top_k()
        if self._search_default_top_k > self._search_max_top_k:
            self._logging_gateway.warning(
                "PgVectorKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k."
            )
            self._search_default_top_k = self._search_max_top_k
        self._snippet_max_chars = self._resolve_snippet_max_chars()
        self._qualified_search_table = qualify_sql_name(
            schema=self._search_schema,
            name=self._search_table,
        )

        self._encoder: SentenceTransformer | None = None
        self._encoder_lock = asyncio.Lock()
        self._encoder_model_name = self._resolve_encoder_model_name()
        self._encoder_max_concurrency = self._resolve_encoder_max_concurrency()
        self._encode_semaphore = asyncio.Semaphore(self._encoder_max_concurrency)

        self._api_timeout_seconds = self._resolve_api_timeout_seconds()
        self._api_max_retries = self._resolve_api_max_retries()
        self._api_retry_backoff_seconds = self._resolve_api_retry_backoff_seconds()

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

    def _resolve_search_schema(self) -> str:
        raw_value = getattr(
            self._section("pgvector", "search"),
            "schema",
            None,
        )
        if raw_value in [None, ""]:
            return resolve_core_rdbms_schema(self._config)
        return validate_sql_identifier(raw_value, label="pgvector.search.schema")

    def _resolve_search_table(self) -> str:
        raw_value = getattr(
            self._section("pgvector", "search"),
            "table",
            None,
        )
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError(
                "Invalid configuration: pgvector.search.table is required."
            )
        return validate_sql_identifier(raw_value, label="pgvector.search.table")

    def _resolve_search_metric(self) -> str:
        raw_value = getattr(
            self._section("pgvector", "search"),
            "metric",
            self._default_search_metric,
        )
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            return self._default_search_metric
        metric = raw_value.strip().lower()
        if metric != "cosine":
            raise RuntimeError(
                "Invalid configuration: pgvector.search.metric must be 'cosine'."
            )
        return metric

    def _resolve_search_default_top_k(self) -> int:
        raw_value = getattr(
            self._section("pgvector", "search"),
            "default_top_k",
            self._default_search_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="pgvector.search.default_top_k",
            default=self._default_search_top_k,
        )

    def _resolve_search_max_top_k(self) -> int:
        raw_value = getattr(
            self._section("pgvector", "search"),
            "max_top_k",
            self._default_search_max_top_k,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="pgvector.search.max_top_k",
            default=self._default_search_max_top_k,
        )

    def _resolve_snippet_max_chars(self) -> int:
        raw_value = getattr(
            self._section("pgvector", "search"),
            "snippet_max_chars",
            self._default_snippet_max_chars,
        )
        return self._parse_positive_int(
            raw_value,
            field_name="pgvector.search.snippet_max_chars",
            default=self._default_snippet_max_chars,
        )

    def _resolve_encoder_model_name(self) -> str:
        raw_value = getattr(
            self._section("pgvector", "encoder"),
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
            self._section("pgvector", "encoder"),
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

    def _resolve_api_timeout_seconds(self) -> float | None:
        raw_value = getattr(
            self._section("pgvector", "api"),
            "timeout_seconds",
            None,
        )
        return parse_optional_positive_finite_float(
            raw_value,
            "pgvector.api.timeout_seconds",
        )

    def _resolve_api_max_retries(self) -> int:
        raw_value = getattr(
            self._section("pgvector", "api"),
            "max_retries",
            self._default_api_max_retries,
        )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            self._logging_gateway.warning(
                "PgVectorKnowledgeGateway: Invalid max_retries configuration."
            )
            return self._default_api_max_retries
        if parsed < 0:
            self._logging_gateway.warning(
                "PgVectorKnowledgeGateway: max_retries must be non-negative."
            )
            return self._default_api_max_retries
        return parsed

    def _resolve_api_retry_backoff_seconds(self) -> float:
        raw_value = getattr(
            self._section("pgvector", "api"),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_value,
            field_name="pgvector.api.retry_backoff_seconds",
            default=self._default_api_retry_backoff_seconds,
        )

    def _build_encoder(self) -> SentenceTransformer:
        return SentenceTransformer(
            model_name_or_path=self._encoder_model_name,
            tokenizer_kwargs={
                "clean_up_tokenization_spaces": False,
            },
            cache_folder=getattr(
                self._section("transformers", "hf"),
                "home",
                None,
            ),
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
    def _vector_literal(vector: list[float]) -> str:
        if not vector:
            raise RuntimeError("Encoded query vector is empty.")
        values = ",".join(str(float(item)) for item in vector)
        return f"[{values}]"

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
    async def _await_with_timeout(
        maybe_awaitable: Awaitable,
        *,
        timeout_seconds: float | None,
    ) -> Any:
        if timeout_seconds is None:
            return await maybe_awaitable
        return await asyncio.wait_for(maybe_awaitable, timeout=timeout_seconds)

    async def _fetch_scalar(
        self,
        statement: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        async with self._engine.connect() as conn:
            result = await self._await_with_timeout(
                conn.execute(sa_text(statement), params or {}),
                timeout_seconds=timeout_seconds,
            )
            return result.scalar_one_or_none()

    async def _fetch_mappings(
        self,
        statement: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            result = await self._await_with_timeout(
                conn.execute(sa_text(statement), params or {}),
                timeout_seconds=timeout_seconds,
            )
            return [dict(row) for row in result.mappings().all()]

    async def _check_database_connectivity(self, *, timeout_seconds: float) -> None:
        value = await self._fetch_scalar(
            "SELECT 1",
            timeout_seconds=timeout_seconds,
        )
        if value != 1:
            raise RuntimeError("PgVector knowledge gateway connectivity check failed.")

    async def _check_vector_extension_enabled(self, *, timeout_seconds: float) -> bool:
        value = await self._fetch_scalar(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')",
            timeout_seconds=timeout_seconds,
        )
        return bool(value)

    async def _check_projection_table_exists(self, *, timeout_seconds: float) -> bool:
        value = await self._fetch_scalar(
            "SELECT to_regclass(:qualified_table)",
            params={"qualified_table": self._qualified_search_table},
            timeout_seconds=timeout_seconds,
        )
        if value in [None, ""]:
            return False
        return True

    async def _fetch_projection_columns(
        self,
        *,
        timeout_seconds: float,
    ) -> dict[str, str]:
        rows = await self._fetch_mappings(
            "SELECT column_name, udt_name "
            "FROM information_schema.columns "
            "WHERE table_schema = :table_schema "
            "AND table_name = :table_name",
            params={
                "table_schema": self._search_schema,
                "table_name": self._search_table,
            },
            timeout_seconds=timeout_seconds,
        )
        return {
            str(row.get("column_name")): str(row.get("udt_name") or "")
            for row in rows
        }

    async def _has_embedding_vector_index(self, *, timeout_seconds: float) -> bool:
        value = await self._fetch_scalar(
            "SELECT EXISTS ("
            "  SELECT 1 "
            "  FROM pg_index idx "
            "  JOIN pg_class tbl ON tbl.oid = idx.indrelid "
            "  JOIN pg_namespace ns ON ns.oid = tbl.relnamespace "
            "  JOIN pg_class ix ON ix.oid = idx.indexrelid "
            "  JOIN pg_am am ON am.oid = ix.relam "
            "  JOIN pg_attribute attr "
            "    ON attr.attrelid = tbl.oid "
            "   AND attr.attnum = ANY(idx.indkey) "
            "  WHERE ns.nspname = :table_schema "
            "    AND tbl.relname = :table_name "
            "    AND attr.attname = 'embedding' "
            "    AND am.amname IN ('ivfflat', 'hnsw')"
            ")",
            params={
                "table_schema": self._search_schema,
                "table_name": self._search_table,
            },
            timeout_seconds=timeout_seconds,
        )
        return bool(value)

    async def check_readiness(self) -> None:
        self._assert_open()
        timeout_seconds = self._api_timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 5.0
        await self._check_database_connectivity(timeout_seconds=timeout_seconds)
        if await self._check_vector_extension_enabled(timeout_seconds=timeout_seconds) is not True:
            raise RuntimeError(
                "PgVector knowledge gateway requires Postgres extension 'vector'."
            )
        if await self._check_projection_table_exists(timeout_seconds=timeout_seconds) is not True:
            raise RuntimeError(
                "PgVector knowledge gateway configured table was not found."
            )
        columns = await self._fetch_projection_columns(timeout_seconds=timeout_seconds)
        missing_columns = sorted(self._required_projection_columns - set(columns))
        if missing_columns:
            missing_text = ", ".join(missing_columns)
            raise RuntimeError(
                "PgVector knowledge gateway table is missing required column(s): "
                f"{missing_text}."
            )
        if columns.get("embedding") != "vector":
            raise RuntimeError(
                "PgVector knowledge gateway embedding column must use vector type."
            )
        if await self._has_embedding_vector_index(timeout_seconds=timeout_seconds) is not True:
            raise RuntimeError(
                "PgVector knowledge gateway requires an ivfflat or hnsw index on embedding."
            )
        try:
            await asyncio.wait_for(self._get_encoder(), timeout=timeout_seconds)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "PgVector knowledge gateway encoder initialization failed."
            ) from exc

    def _build_search_query(
        self,
        *,
        query_vector: str,
        tenant_id: str,
        channel: str | None,
        locale: str | None,
        category: str | None,
        top_k: int,
        min_similarity: float | None,
    ) -> tuple[str, dict[str, Any]]:
        where_conditions: list[str] = [
            "tenant_id = CAST(:tenant_id AS uuid)",
        ]
        params: dict[str, Any] = {
            "query_vector": query_vector,
            "tenant_id": tenant_id,
            "top_k": top_k,
        }
        if channel is not None:
            where_conditions.append("channel = :channel")
            params["channel"] = channel
        if locale is not None:
            where_conditions.append("locale = :locale")
            params["locale"] = locale
        if category is not None:
            where_conditions.append("category = :category")
            params["category"] = category
        if min_similarity is not None:
            where_conditions.append(
                "(1 - (embedding <=> CAST(:query_vector AS vector))) >= :min_similarity"
            )
            params["min_similarity"] = float(min_similarity)

        where_sql = " AND ".join(where_conditions)
        statement = (
            "SELECT "
            "tenant_id, "
            "knowledge_entry_revision_id, "
            "knowledge_pack_version_id, "
            "channel, "
            "locale, "
            "category, "
            "title, "
            "body, "
            "(embedding <=> CAST(:query_vector AS vector)) AS distance "
            f"FROM {self._qualified_search_table} "
            f"WHERE {where_sql} "
            "ORDER BY distance ASC, knowledge_entry_revision_id ASC "
            "LIMIT :top_k"
        )
        return statement, params

    async def _fetch_search_rows(
        self,
        *,
        query_vector: str,
        tenant_id: str,
        channel: str | None,
        locale: str | None,
        category: str | None,
        top_k: int,
        min_similarity: float | None,
    ) -> list[dict[str, Any]]:
        statement, params = self._build_search_query(
            query_vector=query_vector,
            tenant_id=tenant_id,
            channel=channel,
            locale=locale,
            category=category,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        return await self._fetch_mappings(
            statement,
            params=params,
            timeout_seconds=self._api_timeout_seconds,
        )

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
        if not isinstance(value, str):
            return str(value)
        return value

    def _build_snippet(self, *, title: str | None, body: str | None) -> str | None:
        source = body if body not in [None, ""] else title
        if source in [None, ""]:
            return None
        text = str(source)
        if len(text) <= self._snippet_max_chars:
            return text
        return text[: self._snippet_max_chars]

    @staticmethod
    def _uuid_text(value: object) -> str | None:
        if value in [None, ""]:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, str):
            return value
        return str(value)

    def _normalise_item(self, row: dict[str, Any]) -> dict[str, Any]:
        distance = self._coerce_float(row.get("distance"))
        similarity = None if distance is None else float(1.0 - distance)
        title = self._coerce_optional_string(row.get("title"))
        body = self._coerce_optional_string(row.get("body"))
        return {
            "knowledge_entry_revision_id": self._uuid_text(
                row.get("knowledge_entry_revision_id")
            ),
            "knowledge_pack_version_id": self._uuid_text(
                row.get("knowledge_pack_version_id")
            ),
            "tenant_id": self._uuid_text(row.get("tenant_id")),
            "channel": self._coerce_optional_string(row.get("channel")),
            "locale": self._coerce_optional_string(row.get("locale")),
            "category": self._coerce_optional_string(row.get("category")),
            "title": title,
            "snippet": self._build_snippet(
                title=title,
                body=body,
            ),
            "similarity": similarity,
            "distance": distance,
        }

    async def search(
        self,
        params: PgVectorSearchVendorParams,
    ) -> KnowledgeSearchResult:
        self._assert_open()
        tenant_id = self._normalize_tenant_id(params.tenant_id)
        search_term = self._normalize_search_term(params.search_term)
        channel = self._normalize_optional_filter(params.channel)
        locale = self._normalize_optional_filter(params.locale)
        category = self._normalize_optional_filter(params.category)
        top_k = self._resolve_effective_top_k(params.top_k)
        min_similarity = self._normalize_min_similarity(params.min_similarity)

        query_vector = await self._encode_search_term(search_term)
        query_vector_literal = self._vector_literal(query_vector)
        try:
            rows = await self._execute_with_retry(
                operation="search",
                request_factory=lambda: self._fetch_search_rows(
                    query_vector=query_vector_literal,
                    tenant_id=tenant_id,
                    channel=channel,
                    locale=locale,
                    category=category,
                    top_k=top_k,
                    min_similarity=min_similarity,
                ),
            )
        except (SQLAlchemyError, asyncio.TimeoutError) as exc:
            self._logging_gateway.warning(
                "PgVectorKnowledgeGateway transport failure "
                f"(operation=search error={type(exc).__name__}: {exc})"
            )
            raise KnowledgeGatewayRuntimeError(
                provider="pgvector",
                operation="search",
                cause=exc,
            ) from exc
        items = [self._normalise_item(row) for row in rows]
        return KnowledgeSearchResult(
            items=items,
            total_count=None,
            raw_vendor={
                "provider": "pgvector",
                "metric": self._search_metric,
                "table": self._qualified_search_table,
                "result_count": len(items),
                "top_k": top_k,
                "min_similarity": min_similarity,
            },
        )

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
            except (SQLAlchemyError, asyncio.TimeoutError) as exc:
                if attempt >= attempts:
                    raise
                delay_seconds = float(self._api_retry_backoff_seconds) * (
                    2 ** (attempt - 1)
                )
                self._logging_gateway.warning(
                    "PgVectorKnowledgeGateway: transient %s failure; retrying "
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
            raise RuntimeError("PgVector knowledge gateway is closed.")

    async def aclose(self) -> None:
        if self._closed:
            return None
        self._closed = True
        await self._runtime.aclose()
        return None
