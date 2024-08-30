"""Provides an implementation of IIPCService."""

__all__ = ["DefaultIPCService"]

from types import SimpleNamespace

import asyncio

from app.core.contract.ipc_extension import IIPCExtension
from app.core.contract.ipc_service import IIPCService
from app.core.contract.logging_gateway import ILoggingGateway


class DefaultIPCService(IIPCService):
    """An implementation of IIPCService."""

    _ipc_extensions: list[IIPCExtension] = []

    def __init__(
        self,
        config: dict,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = SimpleNamespace(**config)
        self._logging_gateway = logging_gateway

    async def handle_ipc_request(self, ipc_payload: dict) -> None:
        if not self._is_valid_ipc_payload(ipc_payload):
            return

        match ipc_payload["command"]:
            case "get_status":
                await self._handle_get_status(ipc_payload)
                return
            case "cron":
                await self._handle_cron(ipc_payload)
                return
            case _:
                ...
        await ipc_payload["response_queue"].put({"response": "Invalid Command"})

    def register_ipc_extension(self, ext: IIPCExtension) -> None:
        self._ipc_extensions.append(ext)

    async def _handle_get_status(self, payload: dict) -> None:
        """Get assistant status."""
        await payload["response_queue"].put({"response": "OK"})

    async def _handle_cron(self, payload: dict) -> None:
        """Process cron jobs."""
        if self._is_valid_cron_job(payload["data"]):
            hits = 0
            # Process by IPC extensions.
            for ipc_ext in self._ipc_extensions:
                if payload["data"]["command"] in ipc_ext.ipc_commands:
                    await ipc_ext.process_ipc_command(payload)
                    hits += 1
            if hits == 0:
                self._logging_gateway.debug(
                    "DefaultIPCService: No handlers found for command"
                    f" {payload["data"]['command']}."
                )
                await payload["response_queue"].put({"response": "Not Found"})
        else:
            await payload["response_queue"].put({"response": "Invalid Request"})

    def _is_valid_cron_job(self, request_data: dict) -> bool:
        """Valid cron request."""
        if "command" not in request_data.keys():
            return False
        return True

    def _is_valid_ipc_payload(self, payload: dict) -> bool:
        """Validate IPC payload."""
        # Check payload has valid response queue.
        if "response_queue" not in payload.keys() and not isinstance(
            payload["response_queue"], asyncio.Queue
        ):
            return False

        # Check payload has valid command:
        if "command" not in payload.keys():
            return False

        return True
