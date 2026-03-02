"""Provides an abstract base class for IPC services."""

__all__ = [
    "IIPCService",
    "IPCCommandRequest",
    "IPCHandlerResult",
    "IPCAggregateError",
    "IPCAggregateResult",
]

from abc import ABC, abstractmethod

from mugen.core.contract.service.ipc_model import (
    IPCCommandRequest,
    IPCHandlerResult,
    IPCAggregateError,
    IPCAggregateResult,
)


class IIPCService(ABC):
    """An ABC for IPC services."""

    @abstractmethod
    async def handle_ipc_request(
        self,
        request: IPCCommandRequest,
    ) -> IPCAggregateResult:
        """Handle an IPC request from another application."""
