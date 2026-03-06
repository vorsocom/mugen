"""Provides an abstract base class for message handler extensions."""

__all__ = ["IMHExtension"]

from abc import abstractmethod
from typing import Any

from mugen.core.contract.context import ContextScope

from . import IExtensionBase


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
        """Handle a message."""
