"""Provides an abstract base class for Framework (FW) extensions."""

__all__ = ["IFWExtension"]

from abc import abstractmethod

from quart import Quart

from . import IExtensionBase


class IFWExtension(IExtensionBase):  # pylint: disable=too-few-public-methods
    """An ABC for Framework (FW) extensions."""

    @abstractmethod
    async def setup(self, app: Quart) -> None:
        """Perform extension setup."""
