"""Provides an abstract base class for Framework (FW) extensions."""

__all__ = ["IFWExtension"]

from abc import ABC, abstractmethod


class IFWExtension(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for Framework (FW) extensions."""

    @property
    @abstractmethod
    def platforms(self) -> list[str]:
        """Get the platforms that the extension is targeting."""

    @abstractmethod
    async def setup(self) -> None:
        """Perform extension setup."""
