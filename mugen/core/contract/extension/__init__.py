"""Provides an abstract base class for extensions."""

__all__ = ["IExtensionBase"]

from abc import ABC, abstractmethod


class IExtensionBase(ABC):
    """An ABC for extensions."""

    @property
    @abstractmethod
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""

    @abstractmethod
    def platform_supported(self, platform: str) -> bool:
        """Determine if the extension supports the specified platform."""
