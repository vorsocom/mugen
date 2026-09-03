"""Provides an abstract base class for message handler extensions."""

__all__ = ["IMHExtension", "MessageHandlerResponse"]

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from mugen.core.contract.context import ContextScope

from . import IExtensionBase


class MessageHandlerResponse(dict[str, Any]):
    """Dict-compatible MH response with private delivery provenance."""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        delivery_receipt_callback: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        super().__init__(payload)
        self._delivery_receipt_callback = delivery_receipt_callback

    async def emit_delivery_receipt(self, receipt: dict[str, Any]) -> None:
        """Send a sanitized delivery receipt to the originating extension."""
        await self._delivery_receipt_callback(dict(receipt))


class IMHExtension(IExtensionBase):
    """An ABC for message handler extensions."""

    @property
    @abstractmethod
    def message_types(self) -> list[str]:
        """Get the list of message types that the extension handles."""

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    @abstractmethod
    async def handle_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict | str,
        message_context: list[dict] | None = None,
        attachment_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        *,
        scope: ContextScope,
    ) -> list[dict] | None:
        """Handle a message.

        Return ``None`` to decline handling, or a possibly empty list after handling.
        """

    async def handle_delivery_receipt(
        self,
        receipt: dict[str, Any],
        *,
        scope: ContextScope,
    ) -> None:
        """Handle a sanitized receipt for a response produced by this extension."""
