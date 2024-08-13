"""Provides an abstract base class for user services."""

__all__ = ["IUserService"]

from abc import ABC, abstractmethod
from importlib import import_module

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway


class InvalidUserServiceException(Exception):
    """Custom exception."""


class IUserService(ABC):
    """An ABC for user services."""

    _instance = None

    @classmethod
    def instance(
        cls,
        service_module: str,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ):
        """Get an instance of IMessagingService."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                f"Creating new IMessagingService instance: {service_module}."
            )
            import_module(name=service_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidUserServiceException(
                    f"More than one module exists for {service_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or service_module not in str(subclasses[0]):
                raise InvalidUserServiceException(
                    f"{service_module} does not exist or does not subclass "
                    + "IMessagingService."
                )

            cls._instance = subclasses[0](
                keyval_storage_gateway,
                logging_gateway,
            )
        return cls._instance

    @abstractmethod
    def add_known_user(self, user_id: str, displayname: str, room_id: str) -> None:
        """Add a user to the list of known users."""

    @abstractmethod
    def get_known_users_list(self) -> dict:
        """Get the list of known users."""

    @abstractmethod
    def save_known_users_list(self, known_users: dict) -> None:
        """Save a list of known users."""
