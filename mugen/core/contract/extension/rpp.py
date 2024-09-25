"""Provides an abstract base class for RPP extensions."""

__all__ = ["IRPPExtension"]

from abc import ABC, abstractmethod


class IRPPExtension(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for RPP extensions."""

    @property
    @abstractmethod
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""

    @abstractmethod
    async def preprocess_response(
        self,
        attention_thread_key: str,
        user_id: str,
    ) -> tuple[str, bool, bool]:
        """Preprocess the assistant response."""
