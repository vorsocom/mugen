"""Provides an abstract base class for logging gateways."""

__all__ = ["ILoggingGateway"]

from abc import ABC, abstractmethod
from importlib import import_module


class InvalidLoggingGatewayException(Exception):
    """Custom exception."""


class ILoggingGateway(ABC):
    """An ABC for logging gateways."""

    _instance = None

    @classmethod
    def instance(cls, logging_module: str, log_level: int):
        """Get an instance of ILoggingGateway."""
        # Create a new instance.
        if not cls._instance:
            import_module(name=logging_module)
            subclasses = cls.__subclasses__()

            # Raise an exception if multiple subclasses are found.
            if len(subclasses) > 1:
                raise InvalidLoggingGatewayException(
                    f"More than one module exists for {logging_module}: {subclasses}"
                )

            # Raise an exception if no subclasses are found.
            if not subclasses or logging_module not in str(subclasses[0]):
                raise InvalidLoggingGatewayException(
                    f"{logging_module} does not exist or does not subclass "
                    + "ILoggingGateway."
                )

            cls._instance = subclasses[0](log_level)
        return cls._instance

    @abstractmethod
    def critical(self, message: str):
        """Log message with severity CRITICAL (50)."""

    @abstractmethod
    def debug(self, message: str):
        """Log message with severity DEBUG (10)."""

    @abstractmethod
    def error(self, message: str):
        """Log message with severity ERROR (40)."""

    @abstractmethod
    def info(self, message: str):
        """Log message with severity INFO (20)."""

    @abstractmethod
    def warning(self, message: str):
        """Log message with severity WARNING (30)."""
