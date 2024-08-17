"""Provides an abstract base class for NLP services."""

__all__ = ["INLPService"]

from abc import ABC, abstractmethod
from importlib import import_module

from app.contract.logging_gateway import ILoggingGateway


class InvalidNLPServiceException(Exception):
    """Custom exception."""


class INLPService(ABC):
    """An ABC for NLP services."""

    _instance = None

    @classmethod
    def instance(cls, service_module: str, logging_gateway: ILoggingGateway):
        """Get an instance of IIPCService."""
        # Create a new instance.
        if not cls._instance:
            logging_gateway.info(
                f"Creating new INLPService instance: {service_module}."
            )
            import_module(name=service_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidNLPServiceException(
                    f"More than one module exists for {service_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or service_module not in str(subclasses[0]):
                raise InvalidNLPServiceException(
                    f"{service_module} does not exist or does not subclass "
                    + "INLPService."
                )

            cls._instance = subclasses[0](logging_gateway)
        return cls._instance

    @abstractmethod
    def get_keywords(self, text: str) -> list[str]:
        """Do keyword extraction on text."""
