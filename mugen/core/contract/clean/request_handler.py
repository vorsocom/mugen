"""Provides an abstract base class for creating request handlers (use case interactors)."""

__all__ = ["IRequestHandler"]

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from mugen.core.contract.clean.request import IRequest
from mugen.core.contract.clean.response import IResponse

_RequestT = TypeVar("_RequestT", bound=IRequest)
_ResponseT = TypeVar("_ResponseT", bound=IResponse)


# pylint: disable=too-few-public-methods
class IRequestHandler(ABC, Generic[_RequestT, _ResponseT]):
    """A request handler (use case interactor) base class."""

    @abstractmethod
    async def handle(self, request: _RequestT) -> _ResponseT:
        """Handle a request."""
