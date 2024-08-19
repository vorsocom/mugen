"""Provides an abstract base class for IPC services."""

__all__ = ["IIPCService"]

from abc import ABC, abstractmethod
from importlib import import_module

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.meeting_service import IMeetingService
from app.contract.user_service import IUserService


class InvalidIPCServiceException(Exception):
    """Custom exception."""


class IIPCService(ABC):
    """An ABC for IPC services."""

    _instance = None

    # pylint: disable=too-many-arguments
    @classmethod
    def instance(
        cls,
        service_module: str,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        meeting_service: IMeetingService,
        user_service: IUserService,
    ):
        """Get an instance of IIPCService."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                f"Creating new IIPCService instance: {service_module}."
            )
            import_module(name=service_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidIPCServiceException(
                    f"More than one module exists for {service_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or service_module not in str(subclasses[0]):
                raise InvalidIPCServiceException(
                    f"{service_module} does not exist or does not subclass "
                    + "IIPCService."
                )

            cls._instance = subclasses[0](
                keyval_storage_gateway,
                logging_gateway,
                meeting_service,
                user_service,
            )
        return cls._instance

    @abstractmethod
    async def handle_ipc_request(self, ipc_payload: dict) -> None:
        """Handle an IPC request from another application."""
