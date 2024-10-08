"""Provides an abstract base class for Telnet clients."""

__all__ = ["ITelnetClient"]

from abc import ABC, abstractmethod
from types import TracebackType


class ITelnetClient(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for Telnet clients."""

    @abstractmethod
    async def __aenter__(self) -> None:
        """Initialisation routine."""

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Finalisation routine."""

    @abstractmethod
    async def start_server(self) -> None:
        """Start Telnet server."""
