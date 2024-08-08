"""Provides an abstract base class for creating key-value storage gateways."""

__all__ = ["IKeyValStorageGateway"]

from abc import ABC, abstractmethod
from importlib import import_module
from typing import Optional

from app.contract.logging_gateway import ILoggingGateway


class InvalidKeyValStorageGatewayException(Exception):
    """Custom exception."""


class IKeyValStorageGateway(ABC):
    """A key-value storage base class."""

    _instance = None

    @classmethod
    def instance(
        cls, storage_module: str, storage_path: str, logging_gateway: ILoggingGateway
    ):
        """Get an instance of IKeyValStorageGateway."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                f"Creating new IKeyValStorageGateway instance: {storage_module}."
            )
            import_module(name=storage_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidKeyValStorageGatewayException(
                    f"More than one module exists for {storage_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or storage_module not in str(subclasses[0]):
                raise InvalidKeyValStorageGatewayException(
                    f"{storage_module} does not exist or does not subclass "
                    + "IKeyValStorageGateway."
                )

            cls._instance = subclasses[0](storage_path, logging_gateway)
        return cls._instance

    @abstractmethod
    def put(self, key: str, value: str) -> None:
        """Stores a value at the specified key in the key-value store."""

    @abstractmethod
    def get(self, key: str, decode: bool = True) -> Optional[str]:
        """Gets the value stored at key in the key-value."""

    @abstractmethod
    def keys(self) -> list[str]:
        """Get all the keys in the key-value store."""

    @abstractmethod
    def remove(self, key: str) -> Optional[str]:
        """Remove the specified key from the key-value store."""

    @abstractmethod
    def has_key(self, key: str) -> bool:
        """Indicates if the specified key is set in the key-value store."""

    @abstractmethod
    def close(self) -> None:
        """Close the storage instance."""
