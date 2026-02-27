"""Provides an abstract base class for creating requests to send to request handlers."""

__all__ = ["IRequest"]

from abc import ABC
from typing import Generic, TypeVar

from mugen.core.contract.clean.response import IResponse

_ResponseT = TypeVar("_ResponseT", bound=IResponse)


# pylint: disable=too-few-public-methods
class IRequest(ABC, Generic[_ResponseT]):
    """An interactor request base class."""
