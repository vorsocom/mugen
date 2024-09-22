"""Provides an abstract base class for IPC extensions."""

__all__ = ["IIPCExtension"]

from abc import ABC, abstractmethod


class IIPCExtension(ABC):
    """An ABC for IPC extensions."""

    @property
    @abstractmethod
    def ipc_commands(self) -> list[str]:
        """Get the list of ipc commands processed by this provider.."""

    @property
    @abstractmethod
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""

    @abstractmethod
    async def process_ipc_command(self, payload: dict) -> None:
        """Process an IPC command."""
