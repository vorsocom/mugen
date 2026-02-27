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


class _DummyWriterNoPeer:
    def __init__(self):
        self.writes = []
        self.drain = AsyncMock(return_value=None)
        self.close_calls = 0
        self.wait_closed = AsyncMock(return_value=None)

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def close(self) -> None:
        self.close_calls += 1


class _ErrorWriter:
    def __init__(self, *, error: Exception):
        self._error = error
        self.drain = AsyncMock(return_value=None)

    def write(self, _data: bytes) -> None:
        raise self._error


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
        started = Mock()

        with patch(
            "mugen.core.client.telnet.asyncio.start_server",
            new=AsyncMock(return_value=server),
        ) as start_server:
            await client.start_server(started_callback=started)

        start_server.assert_awaited_once_with(
            client._handle_connection, "127.0.0.1", 2323
        )
        server.serve_forever.assert_awaited_once()
        started.assert_called_once_with()
        client._logging_gateway.info.assert_called_once_with(
            "Telnet server running on 127.0.0.1:2323."
        )

    async def test_start_server_without_socket_logs_started_message(self) -> None:
        client = self._new_client()
        server = _DummyServer()
        server.sockets = []

        with patch(
            "mugen.core.client.telnet.asyncio.start_server",
            new=AsyncMock(return_value=server),
        ):
            await client.start_server()

        client._logging_gateway.info.assert_called_once_with("Telnet server started.")

    async def test_resolve_session_identity_handles_missing_peer_and_non_tuple(
        self,
    ) -> None:
        client = self._new_client()

        room_id, sender = client._resolve_session_identity(_DummyWriterNoPeer())  # pylint: disable=protected-access
        self.assertEqual((room_id, sender), ("telnet_room", "telnet_user"))

        writer = _DummyWriter(peername="peer-string")
        room_id, sender = client._resolve_session_identity(writer)  # pylint: disable=protected-access
        self.assertEqual((room_id, sender), ("telnet_room", "telnet_user"))

    async def test_write_returns_false_when_writer_raises(self) -> None:
        client = self._new_client()

        disconnected = await client._write(  # pylint: disable=protected-access
            _ErrorWriter(error=ConnectionError("gone")),
            b"payload",
        )
        self.assertFalse(disconnected)
        client._logging_gateway.debug.assert_called_with(
            "Telnet client disconnected while writing."
        )

    async def test_close_writer_swallows_wait_closed_errors(self) -> None:
        client = self._new_client()
        writer = _DummyWriter()
        writer.wait_closed = AsyncMock(side_effect=RuntimeError("closed"))  # type: ignore[method-assign]

        await client._close_writer(writer)  # pylint: disable=protected-access

        self.assertEqual(writer.close_calls, 1)
        writer.wait_closed.assert_awaited_once()

    async def test_resolve_timeout_and_prompt_limits_handle_invalid_values(self) -> None:
        config = SimpleNamespace(
            telnet=SimpleNamespace(
                socket=SimpleNamespace(host="127.0.0.1", port="2323"),
                read_timeout_seconds="invalid",
                max_prompt_bytes="bad",
            )
        )
        client = DefaultTelnetClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertEqual(client._read_timeout_seconds, 300.0)  # pylint: disable=protected-access
        self.assertEqual(client._max_prompt_bytes, 4096)  # pylint: disable=protected-access

        config.telnet.read_timeout_seconds = 0
        config.telnet.max_prompt_bytes = 0
        client = DefaultTelnetClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=Mock(),
            user_service=Mock(),
        )
        self.assertIsNone(client._read_timeout_seconds)  # pylint: disable=protected-access
        self.assertEqual(client._max_prompt_bytes, 4096)  # pylint: disable=protected-access

    async def test_readline_without_timeout_uses_reader_directly(self) -> None:
        client = self._new_client()
        client._read_timeout_seconds = None  # pylint: disable=protected-access
        reader = _DummyReader([b"hello\n"])

        line = await client._readline(reader)  # pylint: disable=protected-access

        self.assertEqual(line, b"hello\n")

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

    async def test_handle_connection_breaks_when_initial_write_fails(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(return_value=False)  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=b"hello\n")  # pylint: disable=protected-access
        client._handle_text_message = AsyncMock(return_value=["ignored"])
        reader = _DummyReader([b"hello\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._readline.assert_not_awaited()
        client._handle_text_message.assert_not_awaited()
        self.assertEqual(writer.close_calls, 1)

    async def test_handle_connection_ignores_empty_prompt_text(self) -> None:
        client = self._new_client()
        client._handle_text_message = AsyncMock(return_value=["ignored"])
        reader = _DummyReader([b"\n", b".quit\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_not_awaited()
        self.assertGreaterEqual(writer.writes.count(b"~ user: "), 2)

    async def test_handle_connection_breaks_when_assistant_prompt_write_fails(
        self,
    ) -> None:
        client = self._new_client()
        client._write = AsyncMock(side_effect=[True, False])  # pylint: disable=protected-access
        client._handle_text_message = AsyncMock(return_value=["ignored"])
        reader = _DummyReader([b"hello\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_not_awaited()
        self.assertEqual(writer.close_calls, 1)

    async def test_handle_connection_continues_on_empty_text_responses(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(return_value=True)  # pylint: disable=protected-access
        client._readline = AsyncMock(side_effect=[b"hello\n", None])  # pylint: disable=protected-access
        client._handle_text_message = AsyncMock(return_value=[])
        reader = _DummyReader([])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_awaited_once()
        self.assertEqual(client._write.await_count, 3)  # pylint: disable=protected-access
        self.assertEqual(writer.close_calls, 1)

    async def test_handle_connection_breaks_when_response_write_fails(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(side_effect=[True, True, False])  # pylint: disable=protected-access
        client._handle_text_message = AsyncMock(return_value=["OK"])
        reader = _DummyReader([b"hello\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)

        client._handle_text_message.assert_awaited_once()
        self.assertEqual(writer.close_calls, 1)

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
