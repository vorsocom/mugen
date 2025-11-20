"""Provides an implementation of ICPExtension to clear chat history."""

__all__ = ["ClearChatHistoryICPExtension"]

from types import SimpleNamespace

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core import di


class ClearChatHistoryICPExtension(ICPExtension):
    """An implementation of ICPExtension to clear chat history."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config: SimpleNamespace = di.container.config,
        logging_gateway: ILoggingGateway = di.container.logging_gateway,
        messaging_service: IMessagingService = di.container.messaging_service,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return []

    async def process_message(  # pylint: disable=too-many-arguments
        self,
        message: str,
        room_id: str,
        user_id: str,
    ) -> str | None:
        """Process message for commands."""
        if message.strip() == self._config.mugen.commands.clear:
            return self._handle_clear_command(room_id)

    def _handle_clear_command(
        self,
        room_id: str,
    ) -> str:
        # Clear chat history.
        self._messaging_service.clear_chat_history(room_id)
        return "Context cleared."
