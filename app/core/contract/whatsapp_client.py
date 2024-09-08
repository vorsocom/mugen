"""Provides an abstract base class for WhatsApp clients."""

__all__ = ["IWhatsAppClient"]

from abc import ABC, abstractmethod


class IWhatsAppClient(ABC):
    """An ABC for WhatsApp clients."""

    @abstractmethod
    async def listen_forever(self) -> None:
        """Listen for events from the WhatsApp Cloud API."""
