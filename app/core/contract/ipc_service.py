"""Provides an abstract base class for IPC services."""

__all__ = ["IIPCService"]

from abc import ABC, abstractmethod

from app.core.contract.ipc_extension import IIPCExtension


class IIPCService(ABC):
    """An ABC for IPC services."""

    @abstractmethod
    async def handle_ipc_request(self, ipc_payload: dict) -> None:
        """Handle an IPC request from another application."""

    @abstractmethod
    def register_ipc_extension(self, ext: IIPCExtension) -> None:
        """Register an IPC extension with the IPC service."""
