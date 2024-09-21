"""Provides an implementation of IIPCService."""

__all__ = ["DefaultIPCService"]

from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService


class DefaultIPCService(IIPCService):
    """An implementation of IIPCService."""

    _ipc_extensions: list[IIPCExtension] = []

    def __init__(
        self,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._logging_gateway = logging_gateway

    async def handle_ipc_request(self, platform: str, ipc_payload: dict) -> None:
        # Process by IPC extensions.
        hits: int = 0
        for ipc_ext in self._ipc_extensions:
            if ipc_ext.platforms != [] and platform not in ipc_ext.platforms:
                continue

            if ipc_payload["command"] in ipc_ext.ipc_commands:
                await ipc_ext.process_ipc_command(ipc_payload)
                hits += 1
        if hits == 0:
            self._logging_gateway.debug(
                f"No handlers found for IPC command {ipc_payload['command']}."
            )
            await ipc_payload["response_queue"].put({"response": "Not Found"})

    def register_ipc_extension(self, ext: IIPCExtension) -> None:
        self._ipc_extensions.append(ext)
