"""Provides an abstract base class for a meeting service."""

# pylint: disable=too-many-arguments

__all__ = ["IMeetingService"]

from abc import ABC, abstractmethod
from importlib import import_module

from nio import AsyncClient

from app.contract.completion_gateway import ICompletionGateway
from app.contract.platform_gateway import IPlatformGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway


class InvalidMeetingServiceException(Exception):
    """Custom exception."""


class IMeetingService(ABC):
    """A meeting service base class."""

    _instance = None

    @classmethod
    def instance(
        cls,
        service_module: str,
        client: AsyncClient,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        platform_gateway: IPlatformGateway,
    ):
        """Get an instance of IMeetingService."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                f"Creating new IMeetingService instance: {service_module}."
            )
            import_module(name=service_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidMeetingServiceException(
                    f"More than one module exists for {service_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or service_module not in str(subclasses[0]):
                raise InvalidMeetingServiceException(
                    f"{service_module} does not exist or does not subclass "
                    + "IMeetingService."
                )

            cls._instance = subclasses[0](
                client,
                completion_gateway,
                keyval_storage_gateway,
                logging_gateway,
                platform_gateway,
            )
        return cls._instance

    @abstractmethod
    async def cancel_expired_meetings(self) -> None:
        """Cancel all expired meetings."""

    @abstractmethod
    async def cancel_scheduled_meeting(
        self,
        user_id: str,
        chat_id: str,
        chat_thread_key: str,
    ) -> None:
        """Cancel a scheduled meeting."""

    @abstractmethod
    def get_meeting_triggers(self) -> list[str]:
        """Get the list of meeting conversational triggers."""

    @abstractmethod
    def get_scheduled_meetings_data(self, user_id: str) -> str:
        """Get data on scheduled meetings to send to assistant."""

    @abstractmethod
    async def handle_assistant_response(
        self,
        response: str,
        user_id: str,
        room_id: str,
        chat_thread_key: str,
    ) -> None:
        """Check assistant response for conversational triggers."""

    @abstractmethod
    async def schedule_meeting(
        self, user_id: str, chat_id: str, chat_thread_key: str
    ) -> None:
        """Schedule a meeting."""

    @abstractmethod
    async def update_scheduled_meeting(
        self,
        user_id: str,
        chat_id: str,
        chat_thread_key: str,
    ) -> None:
        """Update a scheduled meeting."""
