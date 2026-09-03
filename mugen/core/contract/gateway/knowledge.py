"""Provides provider-neutral contracts for governed knowledge gateways."""

from __future__ import annotations

__all__ = [
    "IKnowledgeGateway",
    "KnowledgeDeleteSelector",
    "KnowledgeGatewayRuntimeError",
    "KnowledgeGatewayWriteResult",
    "KnowledgeIndexDocument",
    "KnowledgeSearchHit",
    "KnowledgeSearchQuery",
    "KnowledgeSearchResult",
]

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import json
from math import isfinite
from typing import Any
import uuid


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _require_uuid(value: uuid.UUID, field_name: str) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{field_name} must be a UUID.")
    return value


@dataclass(slots=True, frozen=True)
class KnowledgeSearchQuery:
    """Provider-neutral, tenant-scoped semantic search request."""

    tenant_id: uuid.UUID
    query_text: str
    knowledge_pack_id: uuid.UUID | None = None
    knowledge_pack_version_id: uuid.UUID | None = None
    channel: str | None = None
    locale: str | None = None
    category: str | None = None
    service_route_key: str | None = None
    client_profile_key: str | None = None
    service_profile_id: uuid.UUID | None = None
    candidate_limit: int = 10
    min_similarity: float | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.tenant_id, "tenant_id")
        query_text = str(self.query_text).strip()
        if not query_text:
            raise ValueError("query_text must be non-empty.")
        object.__setattr__(self, "query_text", query_text)
        for field_name in (
            "knowledge_pack_id",
            "knowledge_pack_version_id",
            "service_profile_id",
        ):
            field_value = getattr(self, field_name)
            if field_value is not None:
                _require_uuid(field_value, field_name)
        for field_name in (
            "channel",
            "locale",
            "category",
            "service_route_key",
            "client_profile_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_optional_text(getattr(self, field_name)),
            )
        if isinstance(self.candidate_limit, bool) or self.candidate_limit <= 0:
            raise ValueError("candidate_limit must be a positive integer.")
        if self.min_similarity is not None:
            similarity = float(self.min_similarity)
            if not isfinite(similarity) or similarity < 0.0 or similarity > 1.0:
                raise ValueError("min_similarity must be between 0 and 1.")
            object.__setattr__(self, "min_similarity", similarity)

    @property
    def search_term(self) -> str:
        """Backward-compatible adapter-facing alias for query text."""
        return self.query_text

    @property
    def top_k(self) -> int:
        """Backward-compatible adapter-facing alias for candidate limit."""
        return self.candidate_limit


@dataclass(slots=True, frozen=True)
class KnowledgeIndexDocument:
    """A deterministic governed document written to a search projection."""

    document_id: str
    tenant_id: uuid.UUID
    knowledge_pack_id: uuid.UUID
    knowledge_pack_version_id: uuid.UUID
    knowledge_entry_id: uuid.UUID
    knowledge_entry_revision_id: uuid.UUID
    knowledge_scope_id: uuid.UUID
    entry_key: str
    title: str
    content: str
    content_checksum: str
    projection_schema_version: int
    channel: str | None = None
    locale: str | None = None
    category: str | None = None
    service_route_key: str | None = None
    client_profile_key: str | None = None
    service_profile_id: uuid.UUID | None = None
    search_content: str | None = None

    def __post_init__(self) -> None:
        if not str(self.document_id).strip():
            raise ValueError("document_id must be non-empty.")
        for field_name in (
            "tenant_id",
            "knowledge_pack_id",
            "knowledge_pack_version_id",
            "knowledge_entry_id",
            "knowledge_entry_revision_id",
            "knowledge_scope_id",
            "service_profile_id",
        ):
            field_value = getattr(self, field_name)
            if field_name == "service_profile_id" and field_value is None:
                continue
            _require_uuid(field_value, field_name)
        for field_name in ("entry_key", "title", "content", "content_checksum"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty.")
        if self.projection_schema_version <= 0:
            raise ValueError("projection_schema_version must be positive.")
        for field_name in (
            "channel",
            "locale",
            "category",
            "service_route_key",
            "client_profile_key",
            "search_content",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_optional_text(getattr(self, field_name)),
            )

    @property
    def index_content(self) -> str:
        """Return retrieval-only text without changing approved response content."""
        return self.search_content or self.content

    def metadata(self) -> dict[str, Any]:
        """Return provider-independent metadata for tenant/scope enforcement."""
        return {
            "tenant_id": str(self.tenant_id),
            "knowledge_pack_id": str(self.knowledge_pack_id),
            "knowledge_pack_version_id": str(self.knowledge_pack_version_id),
            "knowledge_entry_id": str(self.knowledge_entry_id),
            "knowledge_entry_revision_id": str(self.knowledge_entry_revision_id),
            "knowledge_scope_id": str(self.knowledge_scope_id),
            "entry_key": self.entry_key,
            "title": self.title,
            "channel": self.channel,
            "locale": self.locale,
            "category": self.category,
            "service_route_key": self.service_route_key,
            "client_profile_key": self.client_profile_key,
            "service_profile_id": (
                None
                if self.service_profile_id is None
                else str(self.service_profile_id)
            ),
            "content_checksum": self.content_checksum,
            "projection_schema_version": self.projection_schema_version,
        }


@dataclass(slots=True, frozen=True)
class KnowledgeDeleteSelector:
    """A tenant-required selector for idempotent scoped document deletion."""

    tenant_id: uuid.UUID
    knowledge_pack_id: uuid.UUID | None = None
    knowledge_pack_version_id: uuid.UUID | None = None
    document_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_uuid(self.tenant_id, "tenant_id")
        for field_name in ("knowledge_pack_id", "knowledge_pack_version_id"):
            field_value = getattr(self, field_name)
            if field_value is not None:
                _require_uuid(field_value, field_name)
        cleaned_ids = tuple(
            dict.fromkeys(
                str(item).strip() for item in self.document_ids if str(item).strip()
            )
        )
        object.__setattr__(self, "document_ids", cleaned_ids)
        if (
            self.knowledge_pack_id is None
            and self.knowledge_pack_version_id is None
            and not cleaned_ids
        ):
            raise ValueError("A tenant-only cross-pack deletion is not allowed.")


@dataclass(slots=True, frozen=True)
class KnowledgeGatewayWriteResult:
    """Normalized result from an idempotent gateway write or deletion."""

    provider: str
    requested_count: int
    affected_count: int | None = None
    acknowledged: bool = True


@dataclass(slots=True, frozen=True, eq=False)
class KnowledgeSearchHit(Mapping[str, Any]):
    """A typed provider-neutral search hit containing non-authoritative data."""

    tenant_id: uuid.UUID
    knowledge_pack_version_id: uuid.UUID
    knowledge_entry_revision_id: uuid.UUID
    knowledge_pack_id: uuid.UUID | None = None
    knowledge_entry_id: uuid.UUID | None = None
    knowledge_scope_id: uuid.UUID | None = None
    entry_key: str | None = None
    channel: str | None = None
    locale: str | None = None
    category: str | None = None
    service_route_key: str | None = None
    client_profile_key: str | None = None
    service_profile_id: uuid.UUID | None = None
    similarity: float | None = None
    distance: float | None = None
    title: str | None = None
    snippet: str | None = None

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "KnowledgeSearchHit":
        """Coerce normalized provider output into the typed hit contract."""

        def parsed_uuid(key: str, *, required: bool = False) -> uuid.UUID | None:
            value = item.get(key)
            if value in (None, ""):
                if required:
                    raise ValueError(f"Search hit is missing required {key}.")
                return None
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))

        return cls(
            tenant_id=parsed_uuid("tenant_id", required=True),  # type: ignore[arg-type]
            knowledge_pack_id=parsed_uuid("knowledge_pack_id"),
            knowledge_pack_version_id=parsed_uuid(
                "knowledge_pack_version_id", required=True
            ),  # type: ignore[arg-type]
            knowledge_entry_id=parsed_uuid("knowledge_entry_id"),
            knowledge_entry_revision_id=parsed_uuid(
                "knowledge_entry_revision_id", required=True
            ),  # type: ignore[arg-type]
            knowledge_scope_id=parsed_uuid("knowledge_scope_id"),
            entry_key=_normalize_optional_text(item.get("entry_key")),
            channel=_normalize_optional_text(item.get("channel")),
            locale=_normalize_optional_text(item.get("locale")),
            category=_normalize_optional_text(item.get("category")),
            service_route_key=_normalize_optional_text(item.get("service_route_key")),
            client_profile_key=_normalize_optional_text(item.get("client_profile_key")),
            service_profile_id=parsed_uuid("service_profile_id"),
            similarity=(
                None if item.get("similarity") is None else float(item["similarity"])
            ),
            distance=(
                None if item.get("distance") is None else float(item["distance"])
            ),
            title=_normalize_optional_text(item.get("title")),
            snippet=(None if item.get("snippet") is None else str(item.get("snippet"))),
        )

    def _mapping(self) -> dict[str, Any]:
        return {
            "knowledge_entry_revision_id": str(self.knowledge_entry_revision_id),
            "knowledge_pack_version_id": str(self.knowledge_pack_version_id),
            "tenant_id": str(self.tenant_id),
            **(
                {}
                if self.knowledge_pack_id is None
                else {"knowledge_pack_id": str(self.knowledge_pack_id)}
            ),
            **(
                {}
                if self.knowledge_entry_id is None
                else {"knowledge_entry_id": str(self.knowledge_entry_id)}
            ),
            **(
                {}
                if self.knowledge_scope_id is None
                else {"knowledge_scope_id": str(self.knowledge_scope_id)}
            ),
            **({} if self.entry_key is None else {"entry_key": self.entry_key}),
            "channel": self.channel,
            "locale": self.locale,
            "category": self.category,
            **(
                {}
                if self.service_route_key is None
                else {"service_route_key": self.service_route_key}
            ),
            **(
                {}
                if self.client_profile_key is None
                else {"client_profile_key": self.client_profile_key}
            ),
            **(
                {}
                if self.service_profile_id is None
                else {"service_profile_id": str(self.service_profile_id)}
            ),
            "title": self.title,
            "snippet": self.snippet,
            "similarity": self.similarity,
            "distance": self.distance,
        }

    def __getitem__(self, key: str) -> Any:
        return self._mapping()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._mapping())

    def __len__(self) -> int:
        return len(self._mapping())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, KnowledgeSearchHit):
            return self._mapping() == other._mapping()
        if isinstance(other, Mapping):
            return self._mapping() == dict(other)
        return False

    def scope_specificity(self, query: KnowledgeSearchQuery) -> int:
        """Count exact matches; wildcard dimensions contribute zero."""
        score = 0
        for field_name in (
            "channel",
            "locale",
            "category",
            "service_route_key",
            "client_profile_key",
            "service_profile_id",
        ):
            requested = getattr(query, field_name)
            if requested is not None and getattr(self, field_name) == requested:
                score += 1
        return score


@dataclass(slots=True)
class KnowledgeSearchResult:
    """Normalized result from provider-neutral knowledge search operations."""

    items: list[KnowledgeSearchHit | Mapping[str, Any]] = field(default_factory=list)
    total_count: int | None = None
    raw_vendor: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.items = [
            (
                item
                if isinstance(item, KnowledgeSearchHit)
                else KnowledgeSearchHit.from_mapping(item)
            )
            for item in self.items
        ]


class KnowledgeGatewayRuntimeError(RuntimeError):
    """Raised when a knowledge provider fails at runtime."""

    def __init__(
        self,
        *,
        provider: str,
        operation: str,
        cause: BaseException,
    ) -> None:
        self.provider = str(provider)
        self.operation = str(operation)
        self.cause = cause
        super().__init__(
            f"{self.provider} {self.operation} failed: {type(cause).__name__}: {cause}"
        )


class IKnowledgeGateway(ABC):
    """Provider-neutral contract for governed knowledge projections."""

    @property
    def provider_name(self) -> str:
        """Return the stable configured provider token."""
        class_name = type(self).__name__.lower()
        aliases = {
            "chromaknowledgegateway": "chromadb",
            "milvusknowledgegateway": "milvus",
            "pgvectorknowledgegateway": "pgvector",
            "pineconeknowledgegateway": "pinecone",
            "qdrantknowledgegateway": "qdrant",
            "weaviateknowledgegateway": "weaviate",
        }
        return aliases.get(class_name, class_name.removesuffix("knowledgegateway"))

    def configuration_fingerprint(self) -> str:
        """Hash non-secret provider target fields used by the active projection."""
        target_fields = (
            "_search_collection",
            "_search_namespace",
            "_search_schema",
            "_search_table",
            "_search_target_vector",
            "_search_vector_field",
            "_search_metric",
            "_api_host",
            "_api_port",
            "_api_ssl",
            "_api_tenant",
            "_api_database",
            "_api_http_host",
            "_api_http_port",
            "_api_http_secure",
            "_api_grpc_host",
            "_api_grpc_port",
            "_api_grpc_secure",
            "_api_uri",
            "_api_url",
            "_api_index_name",
            "_encoder_model_name",
        )
        descriptor = {
            "provider": self.provider_name,
            **{
                field_name.removeprefix("_"): getattr(self, field_name)
                for field_name in target_fields
                if getattr(self, field_name, None) not in (None, "")
            },
        }
        encoded = json.dumps(descriptor, sort_keys=True, default=str).encode("utf-8")
        return sha256(encoded).hexdigest()

    @abstractmethod
    async def check_readiness(self) -> None:
        """Validate provider readiness for startup fail-fast checks."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close provider resources asynchronously."""

    async def upsert_documents(
        self,
        documents: list[KnowledgeIndexDocument],
    ) -> KnowledgeGatewayWriteResult:
        """Idempotently insert or replace deterministic governed documents."""
        raise NotImplementedError

    async def delete_documents(
        self,
        selector: KnowledgeDeleteSelector,
    ) -> KnowledgeGatewayWriteResult:
        """Idempotently delete documents inside a required tenant scope."""
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: KnowledgeSearchQuery) -> KnowledgeSearchResult:
        """Perform a tenant-required, scope-aware semantic search."""
