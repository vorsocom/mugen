"""Provides an abstract base class for Matrix clients."""

__all__ = ["IMatrixClient"]

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Type

from mugen.core.contract.client.matrix_types import (
    IMatrixSyncSignal,
    MatrixPresence,
    MatrixProfile,
)


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

    @abstractmethod
    async def close(self) -> None:
        """Perform deterministic shutdown cleanup."""

    @property
    @abstractmethod
    def sync_token(self) -> str:
        """Get the next_batch token."""

    synced: IMatrixSyncSignal
    """Sync-ready signal/event populated by concrete adapters."""

    @abstractmethod
    async def sync_forever(
        self,
        *,
        since: str | None = None,
        timeout: int = 100,
        full_state: bool = True,
        set_presence: MatrixPresence = "online",
    ) -> None:
        """Run long-polling sync loop."""

    @abstractmethod
    async def get_profile(self, user_id: str | None = None) -> MatrixProfile:
        """Fetch current profile."""

    @abstractmethod
    async def set_displayname(self, displayname: str) -> None:
        """Set profile display name."""

    @abstractmethod
    async def monitor_runtime_health(self) -> None:
        """Block until a runtime-health failure occurs, then raise it."""

    @abstractmethod
    async def cleanup_known_user_devices_list(self) -> None:
        """Clean up known user devices list."""

    @abstractmethod
    async def trust_known_user_devices(self) -> None:
        """Trust all known user devices."""

    @abstractmethod
    async def verify_user_devices(self, user_id: str) -> None:
        """Verify all of a user's devices."""
