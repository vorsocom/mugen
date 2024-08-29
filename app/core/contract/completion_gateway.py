"""Provides an abstract base class for creating chat completion gateways."""

from typing import Any
from abc import ABC, abstractmethod


# pylint: disable=too-few-public-methods
class ICompletionGateway(ABC):
    """A chat completion gateway base class."""

    @abstractmethod
    async def get_completion(
        self,
        context: list[dict],
        model: str,
        response_format: str,
        temperature: float,
    ) -> Any | None:
        """Get LLM response based on context (conversation history + relevant data)."""
