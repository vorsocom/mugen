"""Provides an abstract base class for creating responses returned from request handlers."""

# pylint: disable=too-few-public-methods

__all__ = ["IResponse"]

from abc import ABC
from typing import Optional


class IResponse(ABC):
    """An interactor response base class."""

    success: bool

    messages: Optional[list[str]] = None

    def __init__(self, success: bool, messages: Optional[list[str]] = None) -> None:
        self.success = success
        self.messages = messages
