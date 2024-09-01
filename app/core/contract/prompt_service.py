"""Provides an abstract base class for prompt services."""

__all__ = ["IPromptService"]

from abc import ABC, abstractmethod


class IPromptService(ABC):
    """An ABC for prompt services"""

    @abstractmethod
    def get_prompt(self, prompt_id: str, model_id: str, use_default: bool) -> str:
        """Get a prompt by it's id."""

    @abstractmethod
    def register_prompt(self, model_id: str, prompt_id: str) -> None:
        """Register a prompt to be served."""
