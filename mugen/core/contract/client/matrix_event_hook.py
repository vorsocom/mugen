"""Serializable matrix event-hook payload contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mugen.core.contract.client.matrix_types import MatrixJSONValue


@dataclass(frozen=True)
class MatrixEventHookPayload:
    """Typed payload for matrix callback events sent over IPC."""

    version: int
    callback: str
    event_type: str
    reason: str
    room_id: str | None
    sender: str | None
    content: dict[str, MatrixJSONValue] | None
    source: dict[str, MatrixJSONValue] | None
    event_id: str | None
    state_key: str | None
    origin_server_ts: int | None

    def to_dict(self) -> dict[str, MatrixJSONValue]:
        """Serialize payload to a plain dictionary for IPC transport."""
        return asdict(self)
