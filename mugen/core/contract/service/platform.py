"""Provides an abstract base class for platform services."""

__all__ = ["IPlatformService"]

from abc import ABC, abstractmethod


class IPlatformService(ABC):
    """An ABC for platform services."""

    @property
    @abstractmethod
    def active_platforms(self) -> list[str]:
        """Get list of active platforms."""

    @abstractmethod
    def extension_supported(self, ext) -> bool:
        """Determine if extension is supported by running instance."""
