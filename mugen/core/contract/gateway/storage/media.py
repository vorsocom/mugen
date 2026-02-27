"""Provides media-storage gateway contracts for web media payloads."""

__all__ = ["IMediaStorageGateway"]

from abc import ABC, abstractmethod


class IMediaStorageGateway(ABC):
    """Abstract interface for media object persistence backends."""

    @abstractmethod
    async def init(self) -> None:
        """Initialize backend runtime state."""

    @abstractmethod
    async def close(self) -> None:
        """Close backend runtime state."""

    @abstractmethod
    async def store_bytes(
        self,
        payload: bytes,
        *,
        filename_hint: str | None = None,
    ) -> str | None:
        """Persist raw bytes and return an opaque media reference."""

    @abstractmethod
    async def store_file(
        self,
        file_path: str,
        *,
        filename_hint: str | None = None,
    ) -> str | None:
        """Persist file content and return an opaque media reference."""

    @abstractmethod
    async def exists(self, media_ref: str) -> bool:
        """Return True when the media reference currently exists."""

    @abstractmethod
    async def materialize(self, media_ref: str) -> str | None:
        """Return a local readable file path for a media reference."""

    @abstractmethod
    async def cleanup(
        self,
        *,
        active_refs: set[str],
        retention_seconds: int,
        now_epoch: float,
    ) -> None:
        """Delete stale, unreferenced media content."""
