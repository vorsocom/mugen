"""Plugin-local Matrix management ports used by IPC admin extensions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IMatrixRoomAdminClient(ABC):
    """Room-management operations required by matrix manager extensions."""

    @property
    @abstractmethod
    def current_user_id(self) -> str:
        """Return current matrix user id."""

    @abstractmethod
    async def joined_room_ids(self) -> list[str]:
        """List currently joined room ids."""

    @abstractmethod
    async def joined_member_ids(self, room_id: str) -> list[str]:
        """List member user ids for a room."""

    @abstractmethod
    async def room_state_events(self, room_id: str) -> list[dict[str, Any]]:
        """List room state events as plain dictionaries."""

    @abstractmethod
    async def direct_room_ids(self) -> set[str]:
        """List known direct-message room ids."""

    @abstractmethod
    async def room_kick(self, room_id: str, user_id: str) -> None:
        """Kick a user from a room."""

    @abstractmethod
    async def room_leave(self, room_id: str) -> None:
        """Leave a room."""


class IMatrixDeviceAdminClient(ABC):
    """Device-management operations required by matrix manager extensions."""

    @property
    @abstractmethod
    def device_id(self) -> str:
        """Return active device id."""

    @abstractmethod
    def device_ed25519_key(self) -> str:
        """Return local device ED25519 verification key."""
