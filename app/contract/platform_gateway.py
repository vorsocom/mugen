"""Provides an abstract base class for creating platform gateways."""

__all__ = ["IPlatformGateway"]

from abc import ABC, abstractmethod
from importlib import import_module
from typing import Optional

from nio import AsyncClient

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway

from app.domain.entity.meeting import Meeting


class InvalidPlatformGatewayException(Exception):
    """Custom exception."""


class IPlatformGateway(ABC):
    """A platform gateway base class."""

    _instance = None

    @classmethod
    def instance(
        cls,
        platform_module: str,
        client: AsyncClient,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ):
        """Get an instance of IPlatformGateway."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                f"Creating new IPlatformGateway instance: {platform_module}."
            )
            import_module(name=platform_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidPlatformGatewayException(
                    f"More than one module exists for {platform_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or platform_module not in str(subclasses[0]):
                raise InvalidPlatformGatewayException(
                    f"{platform_module} does not exist or does not subclass "
                    + "IPlatformGateway."
                )

            cls._instance = subclasses[0](
                client, keyval_storage_gateway, logging_gateway
            )
        return cls._instance

    @abstractmethod
    async def meeting_create_room(self, meeting: Meeting) -> Optional[str]:
        """Create a room to host a meeting."""

    @abstractmethod
    async def meeting_notify_cancel(self, meeting: Meeting) -> bool:
        """Notify attendees of cancelled meeting."""

    @abstractmethod
    async def meeting_notify_invitees(self, meeting: Meeting) -> bool:
        """Notify invitees of scheduled meeting."""

    @abstractmethod
    async def meeting_notify_update(self, meeting: Meeting) -> bool:
        """Notify attendees of updated meeting information."""

    @abstractmethod
    def meeting_persist_data(self, meeting: Meeting) -> None:
        """Persist meeting data to key-value storage."""

    @abstractmethod
    async def meeting_remove(self, meeting: Meeting, initiator: str) -> bool:
        """Remove a scheduled meeting."""

    @abstractmethod
    async def meeting_rollback(self, meeting: Meeting) -> bool:
        """Rollback meeting scheduling."""

    @abstractmethod
    async def meeting_update_room_name(self, meeting: Meeting) -> bool:
        """Change the name of a room create for a scheduled meeting."""

    @abstractmethod
    async def meeting_update_room_note(self, meeting: Meeting) -> bool:
        """Leave a note in the meeting room on the updated meeting information."""

    @abstractmethod
    async def send_text_message(self, room_id: str, content: str) -> bool:
        """Send a text message to a room."""
