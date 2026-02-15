"""Unit tests for mugen.core.client.telnet.DefaultTelnetClient."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from mugen.core.client.telnet import DefaultTelnetClient


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        telnet=SimpleNamespace(
            socket=SimpleNamespace(
                host="127.0.0.1",
                port="2323",
            )
        )
    )


class _DummySocket:
    def getsockname(self):
        return ("127.0.0.1", 2323)


class _DummyServer:
    def __init__(self):
        self.sockets = [_DummySocket()]
        self.serve_forever = AsyncMock(return_value=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        _ = (exc_type, exc_val, exc_tb)
        return False


class _DummyReader:
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _DummyWriter:
    def __init__(self, peername=("127.0.0.1", 50000)):
        self.writes = []
        self.drain = AsyncMock(return_value=None)
        self.close_calls = 0
        self.wait_closed = AsyncMock(return_value=None)
        self._peername = peername

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def close(self) -> None:
        self.close_calls += 1

    def get_extra_info(self, name: str):
        if name == "peername":
            return self._peername
        return None


class _SlowReader:
    async def readline(self):
        await asyncio.sleep(0.01)
        return b"hello\n"


class TestMugenClientTelnet(unittest.IsolatedAsyncioTestCase):
    """Covers telnet client startup, I/O loop, and response fanout."""

    def _new_client(self) -> DefaultTelnetClient:
        logging_gateway = Mock()
        messaging_service = Mock()
        messaging_service.handle_text_message = AsyncMock(return_value=[])
        return DefaultTelnetClient(
            config=_make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=Mock(),
        )

    async def test_enter_and_exit_log_debug(self) -> None:
        client = self._new_client()

        entered = await client.__aenter__()
        exited = await client.__aexit__(None, None, None)

        self.assertIs(entered, client)
        self.assertFalse(exited)
        client._logging_gateway.debug.assert_has_calls(
            [
                call("DefaultTelnetClient.__aenter__"),
                call("DefaultTelnetClient.__aexit__"),
            ]
        )

    async def test_start_server_uses_config_and_runs_forever(self) -> None:
        client = self._new_client()
        server = _DummyServer()

        with patch(
            "mugen.core.client.telnet.asyncio.start_server",
            new=AsyncMock(return_value=server),
        ) as start_server:
            await client.start_server()

        start_server.assert_awaited_once_with(
            client._handle_connection, "127.0.0.1", 2323
        )
        server.serve_forever.assert_awaited_once()
        client._logging_gateway.info.assert_called_once_with(
            "Telnet server running on 127.0.0.1:2323."
        )

    async def test_handle_connection_quit_path(self) -> None:
        client = self._new_client()
        client._handle_text_message = AsyncMock(return_value=["ignored"])
        reader = _DummyReader([b"\\q\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_not_awaited()
        self.assertEqual(writer.writes[0], b"~ user: ")
        self.assertEqual(writer.close_calls, 1)
        writer.wait_closed.assert_awaited_once()
        client._logging_gateway.debug.assert_has_calls(
            [
                call("User connected via telnet"),
                call("User closed telnet connection."),
            ]
        )

    async def test_handle_connection_writes_non_empty_response(self) -> None:
        client = self._new_client()
        client._handle_text_message = AsyncMock(return_value=["OK"])
        reader = _DummyReader([b"hello\n", b".quit\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_awaited_once_with(
            message="hello",
            room_id="telnet_room:127.0.0.1:50000",
            sender="telnet_user:127.0.0.1:50000",
        )
        self.assertIn(b"~ user: ", writer.writes)
        self.assertIn(b"\n~ assistant: ", writer.writes)
        self.assertIn(b"OK\n\n", writer.writes)
        self.assertEqual(writer.close_calls, 1)
        writer.wait_closed.assert_awaited_once()

    async def test_handle_connection_decode_error_closes_writer_and_stops(
        self,
    ) -> None:
        client = self._new_client()
        client._handle_text_message = AsyncMock(return_value=["ignored"])
        reader = _DummyReader([b"\xff\xfe", b".quit\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_not_awaited()
        self.assertEqual(writer.close_calls, 1)
        writer.wait_closed.assert_awaited_once()
        client._logging_gateway.warning.assert_called_once_with(
            "Invalid telnet payload encoding. Closing connection."
        )

    async def test_handle_connection_eof_closes_writer_and_stops(self) -> None:
        client = self._new_client()
        client._handle_text_message = AsyncMock(return_value=["ignored"])
        reader = _DummyReader([b""])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_not_awaited()
        self.assertEqual(writer.close_calls, 1)
        writer.wait_closed.assert_awaited_once()
        client._logging_gateway.debug.assert_any_call("User disconnected from telnet.")

    async def test_handle_connection_timeout_closes_writer_and_stops(self) -> None:
        client = self._new_client()
        client._read_timeout_seconds = 0.001
        client._handle_text_message = AsyncMock(return_value=["ignored"])
        reader = _SlowReader()
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_not_awaited()
        self.assertEqual(writer.close_calls, 1)
        writer.wait_closed.assert_awaited_once()
        client._logging_gateway.debug.assert_any_call(
            "Telnet connection timed out waiting for input."
        )

    async def test_handle_connection_rejects_oversized_prompt(self) -> None:
        client = self._new_client()
        client._max_prompt_bytes = 4
        client._handle_text_message = AsyncMock(return_value=["ignored"])
        reader = _DummyReader([b"hello\n", b".quit\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_not_awaited()
        self.assertIn(b"\n~ assistant: Input too long (max 4 bytes).\n\n", writer.writes)
        client._logging_gateway.warning.assert_any_call(
            "Telnet payload exceeded max prompt size (4 bytes)."
        )

    async def test_handle_text_message_returns_text_responses_only(
        self,
    ) -> None:
        client = self._new_client()
        client._messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "image", "content": "ignored"},
                {"type": "text", "content": "hello"},
                {"type": "text", "content": 42},
                {"type": "text", "content": None},
                "unexpected",
            ]
        )

        text_responses = await client._handle_text_message(
            "hi",
            room_id="r1",
            sender="s1",
        )

        self.assertEqual(text_responses, ["hello", "42"])
        client._messaging_service.handle_text_message.assert_awaited_once_with(
            platform="telnet",
            room_id="r1",
            sender="s1",
            message="hi",
        )
        client._logging_gateway.debug.assert_called_with("Send responses to user.")

        client._messaging_service.handle_text_message = AsyncMock(
            return_value=[{"type": "audio", "content": "ignored"}]
        )
        no_text_response = await client._handle_text_message("hi")
        self.assertEqual(no_text_response, [])
