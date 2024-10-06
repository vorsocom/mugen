"""Provides an abstract base class for Matrix clients."""

__all__ = ["IMatrixClient"]

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Type

from nio import AsyncClient


class IMatrixClient(ABC, AsyncClient):
    """An ABC for MAtrix clients."""

    @abstractmethod
    async def __aenter__(self) -> None:
        """Initialisation routine."""

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Finalisation routine."""

    @property
    @abstractmethod
    def sync_token(self) -> str:
        """Get the next_batch token."""

    @abstractmethod
    def cleanup_known_user_devices_list(self) -> None:
        """Clean up known user devices list."""

    @abstractmethod
    def trust_known_user_devices(self) -> None:
        """Trust all known user devices."""

    @abstractmethod
    def verify_user_devices(self, user_id: str) -> None:
        """Verify all of a user's devices."""
