"""Provides an abstract base class for creating key-value storage gateways."""

__all__ = ["IKeyValStorageGateway"]

from abc import ABC, abstractmethod


class IKeyValStorageGateway(ABC):
    """A key-value storage base class."""

    @abstractmethod
    def put(self, key: str, value: str) -> None:
        """Stores a value at the specified key in the key-value store."""

    @abstractmethod
    def get(self, key: str, decode: bool = True) -> str | None:
        """Gets the value stored at key in the key-value."""

    @abstractmethod
    def keys(self) -> list[str]:
        """Get all the keys in the key-value store."""

    @abstractmethod
    def remove(self, key: str) -> str | None:
        """Remove the specified key from the key-value store."""

    @abstractmethod
    def has_key(self, key: str) -> bool:
        """Indicates if the specified key is set in the key-value store."""

    @abstractmethod
    def close(self) -> None:
        """Close the storage instance."""
