"""Provides an abstract base class for knowledge retrieval gateways."""

__all__ = ["IKnowledgeRetrievalGateway"]

from abc import ABC, abstractmethod
from importlib import import_module

from app.contract.logging_gateway import ILoggingGateway
from app.contract.nlp_service import INLPService


class InvalidKnowledgeRetrievalGatewayException(Exception):
    """Custom exception."""


class IKnowledgeRetrievalGateway(ABC):
    """An ABC for knowledge retrival gateways."""

    _instance = None

    @classmethod
    def instance(
        cls,
        knowledge_retrieval_module: str,
        api_key: str,
        endpoint_url: str,
        logging_gateway: ILoggingGateway,
        nlp_service: INLPService,
    ):
        """Get an instance of IKnowledgeRetrievalGateway."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                "Creating new IKnowledgeRetrievalGateway instance:"
                f" {knowledge_retrieval_module}."
            )
            import_module(name=knowledge_retrieval_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidKnowledgeRetrievalGatewayException(
                    f"More than one module exists for {knowledge_retrieval_module}:"
                    f" {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or knowledge_retrieval_module not in str(subclasses[0]):
                raise InvalidKnowledgeRetrievalGatewayException(
                    f"{knowledge_retrieval_module} does not exist or does not subclass "
                    + "IKnowledgeRetrievalGateway."
                )

            cls._instance = subclasses[0](
                api_key,
                endpoint_url,
                logging_gateway,
                nlp_service,
            )
        return cls._instance

    @abstractmethod
    async def search_similar(
        self,
        collection_name: str,
        dataset: str,
        search_term: str,
        strategy: str,
    ) -> list:
        """Search for documents in the knowledge base containing similar strings."""
