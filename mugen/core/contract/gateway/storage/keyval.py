"""Provides an abstract base class for async key-value storage gateways."""

__all__ = [
    "IKeyValStorageGateway",
    "KeyValBackendError",
    "KeyValConflictError",
    "KeyValEntry",
    "KeyValError",
    "KeyValListPage",
]

from abc import ABC, abstractmethod
import json
from typing import Any

from mugen.core.contract.gateway.storage.keyval_model import (
    KeyValBackendError,
    KeyValConflictError,
    KeyValEntry,
    KeyValError,
    KeyValListPage,
)


class IKeyValStorageGateway(ABC):
    """Async key-value storage contract."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close the storage instance asynchronously."""

    @abstractmethod
    async def get_entry(
        self,
        key: str,
        *,
        namespace: str | None = None,
        include_expired: bool = False,
    ) -> KeyValEntry | None:
        """Get a single key-value entry using typed output."""

    @abstractmethod
    async def put_bytes(
        self,
        key: str,
        value: bytes,
        *,
        namespace: str | None = None,
        codec: str = "bytes",
        expected_row_version: int | None = None,
        ttl_seconds: float | None = None,
    ) -> KeyValEntry:
        """Store raw bytes payload."""

    @abstractmethod
    async def delete(
        self,
        key: str,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
    ) -> KeyValEntry | None:
        """Delete key and return removed entry when present."""

    @abstractmethod
    async def exists(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> bool:
        """Return True when a key exists."""

    @abstractmethod
    async def list_keys(
        self,
        *,
        prefix: str = "",
        namespace: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> KeyValListPage:
        """List keys using prefix and cursor pagination."""

    @abstractmethod
    async def compare_and_set(
        self,
        key: str,
        value: bytes,
        *,
        namespace: str | None = None,
        codec: str = "bytes",
        expected_row_version: int,
        ttl_seconds: float | None = None,
    ) -> KeyValEntry:
        """Conditionally write when expected row version matches."""

    async def get_text(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> str | None:
        """Get a key as UTF-8 text."""
        entry = await self.get_entry(key, namespace=namespace)
        if entry is None:
            return None
        return entry.as_text()

    async def get_json(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        """Get a key decoded as JSON object/list."""
        entry = await self.get_entry(key, namespace=namespace)
        if entry is None:
            return None
        return entry.as_json()

    async def put_text(
        self,
        key: str,
        value: str,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
        ttl_seconds: float | None = None,
    ) -> KeyValEntry:
        """Store a UTF-8 text payload."""
        return await self.put_bytes(
            key,
            value.encode("utf-8"),
            namespace=namespace,
            codec="text/utf-8",
            expected_row_version=expected_row_version,
            ttl_seconds=ttl_seconds,
        )

    async def put_json(
        self,
        key: str,
        value: dict[str, Any] | list[Any],
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
        ttl_seconds: float | None = None,
    ) -> KeyValEntry:
        """Store a JSON object/list payload."""
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return await self.put_bytes(
            key,
            encoded,
            namespace=namespace,
            codec="application/json",
            expected_row_version=expected_row_version,
            ttl_seconds=ttl_seconds,
        )
