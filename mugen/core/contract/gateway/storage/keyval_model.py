"""Typed models and errors for key-value storage contracts."""

__all__ = [
    "KeyValBackendError",
    "KeyValConflictError",
    "KeyValEntry",
    "KeyValError",
    "KeyValListPage",
]

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any


class KeyValError(RuntimeError):
    """Base error for key-value operations."""


class KeyValConflictError(KeyValError):
    """Raised when optimistic concurrency checks fail."""

    def __init__(
        self,
        *,
        namespace: str,
        key: str,
        expected_row_version: int,
        current_row_version: int | None,
    ) -> None:
        super().__init__(
            "Key-value conflict"
            f" namespace={namespace!r} key={key!r}"
            f" expected_row_version={expected_row_version!r}"
            f" current_row_version={current_row_version!r}"
        )
        self.namespace = namespace
        self.key = key
        self.expected_row_version = expected_row_version
        self.current_row_version = current_row_version


class KeyValBackendError(KeyValError):
    """Raised when backend-specific failures occur."""


@dataclass(slots=True, frozen=True)
class KeyValEntry:
    """A normalized key-value entry payload."""

    namespace: str
    key: str
    payload: bytes
    codec: str
    row_version: int
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def as_text(self) -> str | None:
        """Decode payload as UTF-8 text when possible."""
        try:
            return self.payload.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def as_json(self) -> dict[str, Any] | list[Any] | None:
        """Decode payload as UTF-8 JSON object or list when possible."""
        text = self.as_text()
        if text is None:
            return None
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return None
        if isinstance(payload, (dict, list)):
            return payload
        return None


@dataclass(slots=True, frozen=True)
class KeyValListPage:
    """One page of key results from list operations."""

    keys: list[str]
    next_cursor: str | None = None
