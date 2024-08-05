"""Provides an abstract base class for creating requests to send to request handlers."""

__all__ = ["IRequest"]

from abc import ABC
from typing import Generic, TypeVar

_ResponseT = TypeVar("_ResponseT", bound="IRequest")


class IRequest(ABC, Generic[_ResponseT]):
    """An interactor request base class."""
