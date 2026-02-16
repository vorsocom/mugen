"""Provides an abstract base class for creating key-value storage gateways."""

__all__ = ["IKeyValStorageGateway"]

from abc import ABC, abstractmethod


class IKeyValStorageGateway(ABC):
    """A key-value storage base class."""

    @abstractmethod
    def close(self) -> None:
        """Close the storage instance."""

    @abstractmethod
    def get(self, key: str, decode: bool = True) -> str | bytes | None:
        """Get value at key.

        If ``decode`` is True and the value is bytes, implementation should attempt
        UTF-8 decoding. If decoding fails, implementation may return None.
        """

    @abstractmethod
    def has_key(self, key: str) -> bool:
        """Indicates if the specified key is set in the key-value store."""

    @abstractmethod
    def keys(self) -> list[str]:
        """Get all the keys in the key-value store."""

    @abstractmethod
    def put(self, key: str, value: str) -> None:
        """Stores a value at the specified key in the key-value store."""

    @abstractmethod
    def remove(self, key: str) -> str | bytes | None:
        """Remove the specified key from the key-value store."""
