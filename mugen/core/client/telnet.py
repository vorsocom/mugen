"""Provides an implementation of ITelnetClient."""

__all__ = ["DefaultTelnetClient"]

import asyncio
from types import TracebackType

from dependency_injector import providers

from mugen.core.contract.client.telnet import ITelnetClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


class DefaultTelnetClient(ITelnetClient):  # pylint: disable=too-few-public-methods
    """An implementation of ITelnetClient."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config: providers.Configuration = None,  # pylint: disable=c-extension-no-member
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        self._config = config
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

    async def __aenter__(self) -> None:
        self._logging_gateway.debug("DefaultTelnetClient.__aenter__")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        self._logging_gateway.debug("DefaultTelnetClient.__aexit__")

    async def start_server(self) -> None:
        server = await asyncio.start_server(
            self._handle_connection,
            self._config.telnet.socket.host(),
            int(self._config.telnet.socket.port()),
        )
        async with server:
            sock = server.sockets[0].getsockname()
            self._logging_gateway.info(f"Telnet server running on {sock[0]}:{sock[1]}.")
            await server.serve_forever()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._logging_gateway.debug("User connected via telnet")
        while True:
            writer.write("~ user: ".encode())
            await writer.drain()

            prompt = await reader.readline()

            try:
                prompt = prompt.decode("utf-8").strip()
            except UnicodeDecodeError:
                writer.close()

            if prompt in ["\\q", ".quit"]:
                self._logging_gateway.debug("User closed telnet connection.")
                break

            writer.write("\n~ assistant: ".encode())
            await writer.drain()
            response = await self._handle_text_message(prompt)
            if response != "":
                for char in response:
                    await asyncio.sleep(0.01)
                    writer.write(char.encode())
                    await writer.drain()
                writer.write("\n\n".encode())
                await writer.drain()

        writer.close()

    async def _handle_text_message(self, message: str) -> str:
        return await self._messaging_service.handle_text_message(
            platform="cli",
            room_id="telnet_room",
            sender="telnet_user",
            content=message,
        )
