"""Core Matrix contract datatypes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Literal, Protocol

MatrixPresence = Literal["online", "offline", "unavailable"]


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
    raw: Any = field(default=None, repr=False)
