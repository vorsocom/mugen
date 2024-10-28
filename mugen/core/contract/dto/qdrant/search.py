"""Provides a dataclass for specifying Qdrant search parameters."""

__all__ = ["QdrantSearchVendorParams"]

from dataclasses import dataclass

from mugen.core.contract.dto.vendorparams import VendorParams


# pylint: disable=too-many-instance-attributes
@dataclass
class QdrantSearchVendorParams(VendorParams):
    """A dataclass for specifying Qdrant search parameters."""

    collection_name: str

    count: bool = False

    dataset: str = None

    date_from: str = None

    date_to: str = None

    limit: int = 10

    search_term: str

    strategy: str = "must"
