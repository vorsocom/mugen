"""Provides an abstract base class for IPC extensions."""

__all__ = ["IIPCExtension"]

from abc import abstractmethod

from . import IExtensionBase


class IIPCExtension(IExtensionBase):
    """An ABC for IPC extensions."""

    @property
    @abstractmethod
    def ipc_commands(self) -> list[str]:
        """Get the list of ipc commands processed by this provider.."""

    @abstractmethod
    async def process_ipc_command(self, payload: dict) -> None:
        """Process an IPC command."""
