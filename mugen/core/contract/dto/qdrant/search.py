"""Provides a dataclass for specifying Qdrant search parameters."""

__all__ = ["QdrantSearchVendorParams"]

from dataclasses import dataclass
import uuid

from mugen.core.contract.dto.vendorparams import VendorParams


@dataclass
class QdrantSearchVendorParams(VendorParams):
    """A dataclass for specifying Qdrant semantic search parameters."""

    search_term: str
    tenant_id: uuid.UUID
    top_k: int = 10
    min_similarity: float | None = None
    channel: str | None = None
    locale: str | None = None
    category: str | None = None
