"""Provides an abstract base class for creating chat completion gateways."""

from typing import Optional
from importlib import import_module
from abc import ABC, abstractmethod

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway


class InvalidCompletionGatewayException(Exception):
    """Custom exception."""


class ICompletionGateway(ABC):
    """A chat completion gateway base class."""

    _instance = None

    @classmethod
    def instance(
        cls,
        completion_module: str,
        api_key: str,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ):
        """Get an instance of CompletionGateway."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                f"Creating new ICompletionGateway instance: {completion_module}."
            )
            import_module(name=completion_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidCompletionGatewayException(
                    f"More than one module exists for {completion_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or completion_module not in str(subclasses[0]):
                raise InvalidCompletionGatewayException(
                    f"{completion_module} does not exist or does not subclass "
                    + "ICompletionGateway."
                )

            cls._instance = subclasses[0](
                api_key, keyval_storage_gateway, logging_gateway
            )
        return cls._instance

    @staticmethod
    @abstractmethod
    def format_completion(response: Optional[str], default: str) -> str:
        """Format a completion response, returning a default value if it's None."""

    @abstractmethod
    async def classify_message(
        self, message: str, model: str, response_format: str
    ) -> Optional[str]:
        """Classify user messages for RAG pipeline."""

    @abstractmethod
    async def get_completion(
        self, context: list[dict], model: str, response_format: str
    ) -> Optional[str]:
        """Get LLM response based on context (conversation history + relevant data)."""

    @abstractmethod
    def get_scheduled_meetings_data(self, user_id: str) -> str:
        """Get data on scheduled meetings to send to assistant."""
