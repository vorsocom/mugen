"""Provides an abstract base class for IPC extensions."""

__all__ = ["IIPCExtension"]

from abc import abstractmethod

from mugen.core.contract.service.ipc_model import IPCCommandRequest, IPCHandlerResult

from . import IExtensionBase


class IIPCExtension(IExtensionBase):
    """An ABC for IPC extensions."""

    @property
    @abstractmethod
    def ipc_commands(self) -> list[str]:
        """Get the list of ipc commands processed by this provider.."""

    @abstractmethod
    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        """Process an IPC command."""
