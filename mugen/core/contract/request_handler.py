"""Provides an abstract base class for creating request handlers (use case interactors)."""

__all__ = ["IRequestHandler"]

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

_RequestT = TypeVar("_RequestT", bound="IRequestHandler")
_ResponseT = TypeVar("_ResponseT", bound="IRequestHandler")


# pylint: disable=too-few-public-methods
class IRequestHandler(ABC, Generic[_RequestT, _ResponseT]):
    """A request handler (use case interactor) base class."""

    @abstractmethod
    async def handle(self, request: _RequestT) -> _ResponseT:
        """Handle a request."""
