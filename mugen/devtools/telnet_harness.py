"""Development/testing telnet harness."""

__all__ = ["DevTelnetHarnessClient", "run_dev_telnet_server"]

import asyncio
import ipaddress
from collections.abc import Callable
from types import SimpleNamespace, TracebackType

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService

_ALLOWED_ENVIRONMENTS = frozenset({"development", "testing"})
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 2323


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _ipc_provider():
    return di.container.ipc_service


def _keyval_provider():
    return di.container.keyval_storage_gateway


def _messaging_provider():
    return di.container.messaging_service


def _user_provider():
    return di.container.user_service


def _resolve_environment(config: SimpleNamespace) -> str:
    return str(
        getattr(getattr(config, "mugen", SimpleNamespace()), "environment", "")
    ).strip().lower()


def _is_loopback_host(host: object) -> bool:
    if not isinstance(host, str) or host.strip() == "":
        return False
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class DevTelnetHarnessClient:  # pylint: disable=too-few-public-methods
    """A development/testing telnet harness adapter."""

    _default_read_timeout_seconds: float = 300.0
    _default_max_prompt_bytes: int = 4096

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace = None,
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
        self._read_timeout_seconds = self._resolve_read_timeout_seconds()
        self._max_prompt_bytes = self._resolve_max_prompt_bytes()
        self._host = self._resolve_host()
        self._port = self._resolve_port()

    async def __aenter__(self) -> "DevTelnetHarnessClient":
        self._logging_gateway.debug("DevTelnetHarnessClient.__aenter__")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        _ = (exc_type, exc_val, exc_tb)
        self._logging_gateway.debug("DevTelnetHarnessClient.__aexit__")
        return False

    def _resolve_host(self) -> str:
        host = getattr(
            getattr(getattr(self._config, "telnet", None), "socket", None),
            "host",
            _DEFAULT_HOST,
        )
        if not isinstance(host, str) or host.strip() == "":
            host = _DEFAULT_HOST
        resolved = host.strip()
        if _is_loopback_host(resolved) is not True:
            raise RuntimeError(
                "Dev telnet harness must bind to a loopback host "
                "(127.0.0.1, ::1, or localhost)."
            )
        return resolved

    def _resolve_port(self) -> int:
        raw_port = getattr(
            getattr(getattr(self._config, "telnet", None), "socket", None),
            "port",
            _DEFAULT_PORT,
        )
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            port = _DEFAULT_PORT
        if port <= 0:
            port = _DEFAULT_PORT
        return port

    async def start_server(
        self,
        started_callback: Callable[[], None] | None = None,
    ) -> None:
        server = await asyncio.start_server(
            self._handle_connection,
            self._host,
            self._port,
        )
        async with server:
            if server.sockets:
                sock = server.sockets[0].getsockname()
                self._logging_gateway.info(
                    f"Dev telnet harness listening on {sock[0]}:{sock[1]}."
                )
            else:
                self._logging_gateway.info("Dev telnet harness started.")
            if callable(started_callback):
                started_callback()
            await server.serve_forever()

    def _resolve_session_identity(
        self, writer: asyncio.StreamWriter
    ) -> tuple[str, str]:
        room_id = "telnet_room"
        sender = "telnet_user"
        try:
            peer = writer.get_extra_info("peername")
        except AttributeError:
            return room_id, sender

        if isinstance(peer, tuple) and len(peer) >= 2:
            identity = f"{peer[0]}:{peer[1]}"
            return f"{room_id}:{identity}", f"{sender}:{identity}"

        return room_id, sender

    async def _write(
        self,
        writer: asyncio.StreamWriter,
        payload: bytes,
    ) -> bool:
        try:
            writer.write(payload)
            await writer.drain()
            return True
        except (ConnectionError, RuntimeError):
            self._logging_gateway.debug("Telnet client disconnected while writing.")
            return False

    async def _close_writer(self, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except (AttributeError, ConnectionError, RuntimeError):
            ...

    def _resolve_read_timeout_seconds(self) -> float | None:
        raw_timeout = getattr(
            getattr(self._config, "telnet", None),
            "read_timeout_seconds",
            self._default_read_timeout_seconds,
        )
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = self._default_read_timeout_seconds

        if timeout <= 0:
            return None
        return timeout

    def _resolve_max_prompt_bytes(self) -> int:
        raw_limit = getattr(
            getattr(self._config, "telnet", None),
            "max_prompt_bytes",
            self._default_max_prompt_bytes,
        )
        try:
            max_prompt_bytes = int(raw_limit)
        except (TypeError, ValueError):
            max_prompt_bytes = self._default_max_prompt_bytes

        if max_prompt_bytes <= 0:
            return self._default_max_prompt_bytes
        return max_prompt_bytes

    async def _readline(self, reader: asyncio.StreamReader) -> bytes | None:
        try:
            if self._read_timeout_seconds is None:
                return await reader.readline()
            return await asyncio.wait_for(
                reader.readline(),
                timeout=self._read_timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._logging_gateway.debug("Telnet connection timed out waiting for input.")
            return None

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._logging_gateway.debug("User connected via telnet")
        room_id, sender = self._resolve_session_identity(writer)
        try:
            while True:
                if not await self._write(writer, b"~ user: "):
                    break

                prompt = await self._readline(reader)
                if prompt is None:
                    break

                if prompt == b"":
                    self._logging_gateway.debug("User disconnected from telnet.")
                    break

                if len(prompt) > self._max_prompt_bytes:
                    self._logging_gateway.warning(
                        f"Telnet payload exceeded max prompt size ({self._max_prompt_bytes} bytes)."
                    )
                    await self._write(
                        writer,
                        (
                            f"\n~ assistant: Input too long (max "
                            f"{self._max_prompt_bytes} bytes).\n\n"
                        ).encode("utf-8"),
                    )
                    continue

                try:
                    prompt_text = prompt.decode("utf-8").strip()
                except UnicodeDecodeError:
                    self._logging_gateway.warning(
                        "Invalid telnet payload encoding. Closing connection."
                    )
                    break

                if prompt_text in ["\\q", ".quit"]:
                    self._logging_gateway.debug("User closed telnet connection.")
                    break

                if prompt_text == "":
                    continue

                if not await self._write(writer, b"\n~ assistant: "):
                    break

                text_responses = await self._handle_text_message(
                    message=prompt_text,
                    room_id=room_id,
                    sender=sender,
                )
                if not text_responses:
                    continue

                payload = "\n\n".join(text_responses).encode("utf-8") + b"\n\n"
                if not await self._write(writer, payload):
                    break
        finally:
            await self._close_writer(writer)

    async def _handle_text_message(
        self,
        message: str,
        room_id: str = "telnet_room",
        sender: str = "telnet_user",
    ) -> list[str]:
        responses = await self._messaging_service.handle_text_message(
            platform="telnet",
            room_id=room_id,
            sender=sender,
            message=message,
        )

        self._logging_gateway.debug("Send responses to user.")
        text_responses: list[str] = []
        for response in responses or []:
            if not isinstance(response, dict):
                continue
            if response.get("type") != "text":
                continue
            content = response.get("content")
            if content is None:
                continue
            text_responses.append(str(content))

        return text_responses


async def run_dev_telnet_server(
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    ipc_provider=_ipc_provider,
    keyval_provider=_keyval_provider,
    messaging_provider=_messaging_provider,
    user_provider=_user_provider,
    started_callback=None,
) -> None:
    """Run the development/testing telnet harness."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    environment = _resolve_environment(config)
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise RuntimeError(
            "Dev telnet harness is only allowed in development/testing environments."
        )

    harness = DevTelnetHarnessClient(
        config=config,
        ipc_service=ipc_provider(),
        keyval_storage_gateway=keyval_provider(),
        logging_gateway=logger,
        messaging_service=messaging_provider(),
        user_service=user_provider(),
    )
    async with harness as client:
        await client.start_server(started_callback=started_callback)
        logger.debug("Dev telnet harness started.")


def _main() -> None:
    asyncio.run(run_dev_telnet_server())


if __name__ == "__main__":
    _main()

