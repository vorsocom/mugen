"""Provides an abstract base class for messaging services."""

__all__ = ["IMessagingService"]

from abc import ABC, abstractmethod
from importlib import import_module

from nio import AsyncClient

from app.contract.completion_gateway import ICompletionGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.meeting_service import IMeetingService
from app.contract.platform_gateway import IPlatformGateway


class InvalidMessagingServiceException(Exception):
    """Custom exception."""


class IMessagingService(ABC):
    """An abstract base class for messaging services."""

    _instance = None

    @classmethod
    def instance(
        cls,
        service_module: str,
        client: AsyncClient,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        knowledge_retrieval_gateway: IKnowledgeRetrievalGateway,
        logging_gateway: ILoggingGateway,
        platform_gateway: IPlatformGateway,
        meeting_service: IMeetingService,
    ):
        """Get an instance of IMessagingService."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                f"Creating new IMessagingService instance: {service_module}."
            )
            import_module(name=service_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidMessagingServiceException(
                    f"More than one module exists for {service_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or service_module not in str(subclasses[0]):
                raise InvalidMessagingServiceException(
                    f"{service_module} does not exist or does not subclass "
                    + "IMessagingService."
                )

            cls._instance = subclasses[0](
                client,
                completion_gateway,
                keyval_storage_gateway,
                knowledge_retrieval_gateway,
                logging_gateway,
                platform_gateway,
                meeting_service,
            )
        return cls._instance

    @abstractmethod
    async def handle_text_message(
        self,
        room_id: str,
        message_id: str,
        sender: str,
        content: str,
        known_users_list_key: str,
    ) -> None:
        """Handle a text message from a chat."""
