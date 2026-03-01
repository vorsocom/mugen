"""Provides an abstract base class for knowledge gateways."""

__all__ = [
    "IKnowledgeGateway",
    "KnowledgeGatewayRuntimeError",
    "KnowledgeSearchResult",
]

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


class IKnowledgeGateway(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for knowledge retrival gateways."""

    @abstractmethod
    async def check_readiness(self) -> None:
        """Validate provider readiness for startup fail-fast checks."""

    @abstractmethod
    async def search(self, params: VendorParams) -> KnowledgeSearchResult:
        """Perform knwoledge lookup."""
