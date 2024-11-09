"""Provides a dataclass for specifying Qdrant search parameters."""

__all__ = ["QdrantSearchVendorParams"]

from dataclasses import dataclass, field

from mugen.core.contract.dto.vendorparams import VendorParams


# pylint: disable=too-many-instance-attributes
@dataclass
class QdrantSearchVendorParams(VendorParams):
    """A dataclass for specifying Qdrant search parameters."""

    collection_name: str

    search_term: str

    count: bool = False

    dataset: str = None

    date_from: str = None

    date_to: str = None

    keywords: list[str] = field(default_factory=list)

    limit: int = 10

    strategy: str = "must"
