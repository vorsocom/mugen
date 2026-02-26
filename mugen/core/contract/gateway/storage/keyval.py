"""Provides an abstract base class for creating key-value storage gateways."""

__all__ = [
    "IKeyValStorageGateway",
    "KeyValBackendError",
    "KeyValConflictError",
    "KeyValEntry",
    "KeyValError",
    "KeyValListPage",
]

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
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
    """A key-value storage base class."""

    @abstractmethod
    def close(self) -> None:
        """Close the storage instance."""

    @abstractmethod
    def get(self, key: str, decode: bool = True) -> str | bytes | None:
        """Legacy sync get operation."""

    @abstractmethod
    def has_key(self, key: str) -> bool:
        """Legacy sync membership check."""

    @abstractmethod
    def keys(self) -> list[str]:
        """Legacy sync key enumeration."""

    @abstractmethod
    def put(self, key: str, value: str | bytes) -> None:
        """Legacy sync put operation."""

    @abstractmethod
    def remove(self, key: str) -> str | bytes | None:
        """Legacy sync delete operation."""

    async def aclose(self) -> None:
        """Close the storage instance asynchronously."""
        await asyncio.to_thread(self.close)

    async def get_entry(
        self,
        key: str,
        *,
        namespace: str | None = None,
        include_expired: bool = False,  # pylint: disable=unused-argument
    ) -> KeyValEntry | None:
        """Get one key-value entry using normalized typed output."""
        raw = await asyncio.to_thread(self.get, key, False)
        if raw is None:
            return None

        payload: bytes
        codec: str
        if isinstance(raw, bytes):
            payload = raw
            codec = "bytes"
        elif isinstance(raw, str):
            payload = raw.encode("utf-8")
            codec = "text/utf-8"
        else:
            payload = str(raw).encode("utf-8")
            codec = "text/utf-8"

        return KeyValEntry(
            namespace=namespace or "default",
            key=key,
            payload=payload,
            codec=codec,
            row_version=1,
        )

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
        """Store a raw payload."""
        if expected_row_version is not None:
            return await self.compare_and_set(
                key,
                value,
                namespace=namespace,
                codec=codec,
                expected_row_version=expected_row_version,
                ttl_seconds=ttl_seconds,
            )

        if codec in {"text/utf-8", "application/json"}:
            await asyncio.to_thread(self.put, key, value.decode("utf-8"))
        else:
            await asyncio.to_thread(self.put, key, value)

        entry = await self.get_entry(key, namespace=namespace)
        if entry is None:
            raise KeyValBackendError(
                f"Write verification failed for namespace={namespace!r} key={key!r}."
            )

        return entry

    async def delete(
        self,
        key: str,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
    ) -> KeyValEntry | None:
        """Delete a key and return removed entry when present."""
        if expected_row_version is not None:
            raise KeyValConflictError(
                namespace=namespace or "default",
                key=key,
                expected_row_version=expected_row_version,
                current_row_version=None,
            )

        removed = await asyncio.to_thread(self.remove, key)
        if removed is None:
            return None

        payload: bytes
        codec: str
        if isinstance(removed, bytes):
            payload = removed
            codec = "bytes"
        else:
            payload = str(removed).encode("utf-8")
            codec = "text/utf-8"

        return KeyValEntry(
            namespace=namespace or "default",
            key=key,
            payload=payload,
            codec=codec,
            row_version=1,
        )

    async def exists(
        self,
        key: str,
        *,
        namespace: str | None = None,  # pylint: disable=unused-argument
    ) -> bool:
        """Return True if key exists."""
        return bool(await asyncio.to_thread(self.has_key, key))

    async def list_keys(
        self,
        *,
        prefix: str = "",
        namespace: str | None = None,  # pylint: disable=unused-argument
        limit: int | None = None,
        cursor: str | None = None,
    ) -> KeyValListPage:
        """List keys by prefix with cursor pagination."""
        raw_keys = await asyncio.to_thread(self.keys)
        filtered = [k for k in raw_keys if k.startswith(prefix)]
        filtered.sort()

        start_index = 0
        if cursor not in [None, ""]:
            for index, item in enumerate(filtered):
                if item > str(cursor):
                    start_index = index
                    break
            else:
                return KeyValListPage(keys=[], next_cursor=None)

        page_limit = int(limit or len(filtered) or 1)
        if page_limit <= 0:
            page_limit = 1

        page_keys = filtered[start_index : start_index + page_limit]
        next_cursor: str | None = None
        if (start_index + page_limit) < len(filtered):
            next_cursor = page_keys[-1]

        return KeyValListPage(keys=page_keys, next_cursor=next_cursor)

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
        existing = await self.get_entry(key, namespace=namespace)
        current_version = 0 if existing is None else int(existing.row_version)
        if current_version != int(expected_row_version):
            raise KeyValConflictError(
                namespace=namespace or "default",
                key=key,
                expected_row_version=expected_row_version,
                current_row_version=current_version,
            )

        if codec in {"text/utf-8", "application/json"}:
            await asyncio.to_thread(self.put, key, value.decode("utf-8"))
        else:
            await asyncio.to_thread(self.put, key, value)

        updated = await self.get_entry(key, namespace=namespace)
        if updated is None:
            raise KeyValBackendError(
                f"CAS write verification failed for namespace={namespace!r} key={key!r}."
            )

        expires_at = None
        if ttl_seconds is not None and ttl_seconds > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=float(ttl_seconds))

        return KeyValEntry(
            namespace=updated.namespace,
            key=updated.key,
            payload=updated.payload,
            codec=updated.codec,
            row_version=int(expected_row_version) + 1,
            expires_at=expires_at,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        )
