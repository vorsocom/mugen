"""Provides an implementation of IIPCService."""

__all__ = ["DefaultIPCService"]

import asyncio

from app.contract.ipc_service import IIPCService
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.user_service import IUserService


class DefaultIPCService(IIPCService):
    """An implementation of IIPCService."""

    def __init__(
        self,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        user_service: IUserService,
    ) -> None:
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._user_service = user_service

    async def handle_ipc_request(self, ipc_payload: dict) -> None:
        if "command" in ipc_payload.keys():
            match ipc_payload["command"]:
                case "get_status":
                    if "response_queue" in ipc_payload.keys() and isinstance(
                        ipc_payload["response_queue"], asyncio.Queue
                    ):
                        await ipc_payload["response_queue"].put(
                            {"response": self._get_status()}
                        )
                    return
                case _:
                    ...

        if "response_queue" in ipc_payload.keys() and isinstance(
            ipc_payload["response_queue"], asyncio.Queue
        ):
            await ipc_payload["response_queue"].put({"response": "Invalid Command"})

    def _get_status(self) -> str | dict:
        """Get assistant status."""
        return "OK"
