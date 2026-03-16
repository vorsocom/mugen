"""Provides a dataclass for specifying pgvector search parameters."""

__all__ = ["PgVectorSearchVendorParams"]

from dataclasses import dataclass
import uuid

from mugen.core.contract.dto.vendorparams import VendorParams


@dataclass
class PgVectorSearchVendorParams(VendorParams):
    """A dataclass for specifying pgvector semantic search parameters."""

    search_term: str
    tenant_id: uuid.UUID
    top_k: int = 10
    min_similarity: float | None = None
    channel: str | None = None
    locale: str | None = None
    category: str | None = None
