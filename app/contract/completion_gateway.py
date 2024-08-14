"""Provides an abstract base class for creating chat completion gateways."""

from typing import Any, Optional
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

    @abstractmethod
    async def get_chat_thread_classification(
        self, context: list[dict], message: str, model: str, response_format: str
    ) -> Optional[str]:
        """Given a user message and a chat thread, classify them as related or unrelated."""

    @abstractmethod
    async def get_completion(
        self, context: list[dict], model: str, response_format: str
    ) -> Optional[Any]:
        """Get LLM response based on context (conversation history + relevant data)."""

    @abstractmethod
    async def get_rag_classification_gdf_knowledge(
        self, message: str, model: str, response_format: str
    ) -> Optional[str]:
        """Classify user messages for GDF Knowledge RAG pipeline."""

    @abstractmethod
    async def get_rag_classification_orders(
        self, user: str, message: str, model: str, response_format: str
    ) -> Optional[str]:
        """Classify user messages for orders RAG pipeline."""
