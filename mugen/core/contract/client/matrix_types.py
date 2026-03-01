"""Core Matrix contract datatypes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Literal, Protocol, TypeAlias

MatrixPresence = Literal["online", "offline", "unavailable"]
MatrixMetadataValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | dict[str, "MatrixMetadataValue"]
    | list["MatrixMetadataValue"]
)


class IMatrixSyncSignal(Protocol):
    """Minimal sync-signal contract exposed by matrix adapters."""

    async def wait(self) -> None:
        """Block until sync readiness is reached."""

    def clear(self) -> None | Awaitable[None]:
        """Clear sync readiness signal state."""


@dataclass(frozen=True)
class MatrixProfile:
    """Adapter-neutral Matrix profile payload."""

    user_id: str | None = None
    displayname: str | None = None
    avatar_url: str | None = None
    metadata: dict[str, MatrixMetadataValue] = field(default_factory=dict)
