"""Provides an abstract base class for creating chat completion gateways."""

from typing import Any
from abc import ABC, abstractmethod


class ICompletionGateway(ABC):  # pylint: disable=too-few-public-methods
    """A chat completion gateway base class."""

    @abstractmethod
    async def get_completion(
        self,
        context: list[dict],
        operation: str,
    ) -> Any | None:
        """Get LLM response based on context (conversation history + relevant data)."""
