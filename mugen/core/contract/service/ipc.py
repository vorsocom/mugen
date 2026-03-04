"""Provides an abstract base class for IPC services."""

__all__ = [
    "IIPCService",
    "IPCCommandRequest",
    "IPCHandlerResult",
    "IPCAggregateError",
    "IPCAggregateResult",
    "IPCCriticalDispatchError",
]

from abc import ABC, abstractmethod

from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.service.ipc_model import (
    IPCCommandRequest,
    IPCHandlerResult,
    IPCAggregateError,
    IPCAggregateResult,
    IPCCriticalDispatchError,
)


class IIPCService(ABC):
    """An ABC for IPC services."""

    @abstractmethod
    def bind_ipc_extension(
        self,
        ext: IIPCExtension,
        *,
        critical: bool = False,
    ) -> None:
        """Bind an IPC extension to the service runtime."""

    @abstractmethod
    async def handle_ipc_request(
        self,
        request: IPCCommandRequest,
    ) -> IPCAggregateResult:
        """Handle an IPC request from another application."""
