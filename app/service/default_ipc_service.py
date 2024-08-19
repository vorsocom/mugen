"""Provides an implementation of IIPCService."""

__all__ = ["DefaultIPCService"]

import asyncio

from app.contract.ipc_service import IIPCService
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.meeting_service import IMeetingService
from app.contract.user_service import IUserService


class DefaultIPCService(IIPCService):
    """An implementation of IIPCService."""

    def __init__(
        self,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        meeting_service: IMeetingService,
        user_service: IUserService,
    ) -> None:
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._meeting_service = meeting_service
        self._user_service = user_service

    async def handle_ipc_request(self, ipc_payload: dict) -> None:
        if not self._is_valid_ipc_payload(ipc_payload):
            return

        if "command" in ipc_payload.keys():
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

    async def _handle_get_status(self, payload: dict) -> None:
        """Get assistant status."""
        await payload["response_queue"].put({"response": "OK"})

    async def _handle_cron(self, payload: dict) -> None:
        """Process cron jobs."""
        request_data = payload["data"]
        if self._is_valid_cron_job(request_data):
            match request_data["command"]:
                case "meeting_delete_expired":
                    await self._meeting_service.cancel_expired_meetings()
                    await payload["response_queue"].put({"response": "OK"})
                    return
                case _:
                    ...
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
