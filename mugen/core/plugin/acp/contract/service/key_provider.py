"""Contracts for key material provider implementations."""

__all__ = [
    "ResolvedKeyMaterial",
    "IKeyMaterialProvider",
]

from abc import ABC, abstractmethod
from dataclasses import dataclass

from mugen.core.plugin.acp.domain import KeyRefDE


@dataclass(frozen=True)
class ResolvedKeyMaterial:
    """Resolved secret material for a specific key reference."""

    key_id: str
    secret: bytes
    provider: str


class IKeyMaterialProvider(ABC):
    """Provider contract for resolving key material from a KeyRef entry."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier used by KeyRef.provider."""

    @abstractmethod
    def resolve(self, key_ref: KeyRefDE) -> bytes | None:
        """Resolve key material for the provided key reference."""
