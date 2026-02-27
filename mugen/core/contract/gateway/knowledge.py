"""Provides an abstract base class for knowledge gateways."""

__all__ = ["IKnowledgeGateway", "KnowledgeSearchResult"]

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from mugen.core.contract.dto.vendorparams import VendorParams


@dataclass(slots=True, frozen=True)
class KnowledgeSearchResult:
    """Normalized result from knowledge search operations."""

    items: list[dict[str, Any]] = field(default_factory=list)
    total_count: int | None = None
    raw_vendor: dict[str, Any] | None = None


class IKnowledgeGateway(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for knowledge retrival gateways."""

    @abstractmethod
    async def search(self, params: VendorParams) -> KnowledgeSearchResult:
        """Perform knwoledge lookup."""
