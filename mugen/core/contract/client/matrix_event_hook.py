"""Serializable matrix event-hook payload contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MatrixEventHookPayload:
    """Typed payload for matrix callback events sent over IPC."""

    version: int
    callback: str
    event_type: str
    reason: str
    room_id: str | None
    sender: str | None
    content: dict[str, Any] | None
    source: dict[str, Any] | None
    event_id: str | None
    state_key: str | None
    origin_server_ts: int | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize payload to a plain dictionary for IPC transport."""
        return asdict(self)
