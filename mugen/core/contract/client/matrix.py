"""Provides an abstract base class for Matrix clients."""

__all__ = ["IMatrixClient"]

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any
from typing import Type


class IMatrixClient(ABC):
    """A core Matrix client port without vendor SDK inheritance."""

    @abstractmethod
    async def __aenter__(self) -> "IMatrixClient":
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

    synced: Any
    """Sync-ready signal/event populated by concrete adapters."""

    async def sync_forever(self, *args, **kwargs) -> Any:
        """Run long-polling sync loop."""
        raise NotImplementedError

    async def get_profile(self, *args, **kwargs) -> Any:
        """Fetch current profile."""
        raise NotImplementedError

    async def set_displayname(self, *args, **kwargs) -> Any:
        """Set profile display name."""
        raise NotImplementedError

    @abstractmethod
    async def cleanup_known_user_devices_list(self) -> None:
        """Clean up known user devices list."""

    @abstractmethod
    async def trust_known_user_devices(self) -> None:
        """Trust all known user devices."""

    @abstractmethod
    async def verify_user_devices(self, user_id: str) -> None:
        """Verify all of a user's devices."""
