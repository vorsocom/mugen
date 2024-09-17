"""Provides an abstract base class for logging gateways."""

__all__ = ["ILoggingGateway"]

from abc import ABC, abstractmethod


class ILoggingGateway(ABC):
    """An ABC for logging gateways."""

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
