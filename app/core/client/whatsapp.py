"""Provides an implementation of IWhatsApp client."""

__all__ = ["DefaultWhatsAppClient"]

import asyncio
from types import SimpleNamespace

from app.core.contract.ipc_service import IIPCService
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.messaging_service import IMessagingService
from app.core.contract.user_service import IUserService
from app.core.contract.whatsapp_client import IWhatsAppClient


# pylint: disable=too-many-instance-attributes
class DefaultWhatsAppClient(IWhatsAppClient):
    """An implementation of IWhatsAppClient."""

    _stop_listening: bool = False

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: dict = None,
        ipc_queue: asyncio.Queue = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        self._config = SimpleNamespace(**config)
        self._ipc_queue = ipc_queue
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

    async def __aenter__(self) -> None:
        """Initialisation."""
        self._logging_gateway.debug("DefaultWhatsAppClient.__aenter__")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Finalisation."""
        self._logging_gateway.debug("DefaultWhatsAppClient.__aexit__")
        self._stop_listening = True

    async def listen_forever(self) -> None:
        # Loop until exit.
        while not self._stop_listening:
            try:
                while not self._ipc_queue.empty():
                    payload = await self._ipc_queue.get()
                    asyncio.create_task(self._ipc_service.handle_ipc_request(payload))
                    self._ipc_queue.task_done()

                await asyncio.sleep(0)
            except asyncio.exceptions.CancelledError:
                self._logging_gateway.debug("WhatsApp listen_forever loop exited.")
                break
