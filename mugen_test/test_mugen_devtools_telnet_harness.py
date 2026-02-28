"""Unit tests for mugen.devtools.telnet_harness."""

from __future__ import annotations

import asyncio
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from mugen.devtools import telnet_harness as harness_mod
from mugen.devtools.telnet_harness import DevTelnetHarnessClient, run_dev_telnet_server


def _make_config(
    *,
    environment: str = "development",
    host: str = "127.0.0.1",
    port: str = "2323",
    read_timeout_seconds: object = 300.0,
    max_prompt_bytes: object = 4096,
) -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(environment=environment),
        telnet=SimpleNamespace(
            socket=SimpleNamespace(
                host=host,
                port=port,
            ),
            read_timeout_seconds=read_timeout_seconds,
            max_prompt_bytes=max_prompt_bytes,
        ),
    )


class _DummySocket:
    def getsockname(self):
        return ("127.0.0.1", 2323)


class _DummyServer:
    def __init__(self, *, with_socket: bool = True):
        self.sockets = [_DummySocket()] if with_socket else []
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
    def __init__(self):
        self.writes = []
        self.drain = AsyncMock(return_value=None)
        self.close_calls = 0
        self.wait_closed = AsyncMock(return_value=None)

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def close(self) -> None:
        self.close_calls += 1

    def get_extra_info(self, name: str):
        if name == "peername":
            return ("127.0.0.1", 50000)
        return None


class _DummyWriterNoPeer:
    def get_extra_info(self, _name: str):
        raise AttributeError("peer unavailable")


class _DummyWriterPeerString:
    def get_extra_info(self, _name: str):
        return "peer-string"


class TestDevTelnetHarnessClient(unittest.IsolatedAsyncioTestCase):
    """Covers development telnet harness startup and I/O loop."""

    def _new_client(self, *, config: SimpleNamespace | None = None) -> DevTelnetHarnessClient:
        messaging_service = Mock()
        messaging_service.handle_text_message = AsyncMock(return_value=[{"type": "text", "content": "ok"}])
        return DevTelnetHarnessClient(
            config=config or _make_config(),
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=Mock(),
            messaging_service=messaging_service,
            user_service=Mock(),
        )

    async def test_constructor_rejects_non_loopback_host(self) -> None:
        with self.assertRaises(RuntimeError):
            self._new_client(config=_make_config(host="0.0.0.0"))

    async def test_start_server_uses_host_and_port(self) -> None:
        client = self._new_client()
        server = _DummyServer()
        started = Mock()

        with patch(
            "mugen.devtools.telnet_harness.asyncio.start_server",
            new=AsyncMock(return_value=server),
        ) as start_server:
            await client.start_server(started_callback=started)

        start_server.assert_awaited_once_with(client._handle_connection, "127.0.0.1", 2323)  # pylint: disable=protected-access
        server.serve_forever.assert_awaited_once()
        started.assert_called_once_with()

    async def test_handle_connection_routes_messages_to_messaging_service(self) -> None:
        client = self._new_client()
        reader = _DummyReader([b"hello\n", b".quit\n"])
        writer = _DummyWriter()

        await client._handle_connection(reader, writer)  # pylint: disable=protected-access

        client._messaging_service.handle_text_message.assert_awaited()  # pylint: disable=protected-access
        self.assertIn(b"~ user: ", writer.writes)
        self.assertEqual(writer.close_calls, 1)
        writer.wait_closed.assert_awaited_once()

    async def test_enter_exit_logging(self) -> None:
        client = self._new_client()
        entered = await client.__aenter__()
        exited = await client.__aexit__(None, None, None)
        self.assertIs(entered, client)
        self.assertFalse(exited)
        client._logging_gateway.debug.assert_has_calls(  # pylint: disable=protected-access
            [
                call("DevTelnetHarnessClient.__aenter__"),
                call("DevTelnetHarnessClient.__aexit__"),
            ]
        )

    async def test_helper_providers_read_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="log",
            ipc_service="ipc",
            keyval_storage_gateway="kv",
            messaging_service="msg",
            user_service="usr",
        )
        with patch.object(harness_mod.di, "container", container):
            self.assertEqual(harness_mod._config_provider(), "cfg")  # pylint: disable=protected-access
            self.assertEqual(harness_mod._logger_provider(), "log")  # pylint: disable=protected-access
            self.assertEqual(harness_mod._ipc_provider(), "ipc")  # pylint: disable=protected-access
            self.assertEqual(harness_mod._keyval_provider(), "kv")  # pylint: disable=protected-access
            self.assertEqual(harness_mod._messaging_provider(), "msg")  # pylint: disable=protected-access
            self.assertEqual(harness_mod._user_provider(), "usr")  # pylint: disable=protected-access

    async def test_environment_and_loopback_helpers(self) -> None:
        self.assertEqual(
            harness_mod._resolve_environment(SimpleNamespace()),  # pylint: disable=protected-access
            "",
        )
        self.assertEqual(
            harness_mod._resolve_environment(  # pylint: disable=protected-access
                SimpleNamespace(mugen=SimpleNamespace(environment=" Development "))
            ),
            "development",
        )
        self.assertFalse(harness_mod._is_loopback_host(None))  # pylint: disable=protected-access
        self.assertFalse(harness_mod._is_loopback_host(""))  # pylint: disable=protected-access
        self.assertTrue(harness_mod._is_loopback_host("localhost"))  # pylint: disable=protected-access
        self.assertTrue(harness_mod._is_loopback_host("::1"))  # pylint: disable=protected-access
        self.assertFalse(harness_mod._is_loopback_host("example.com"))  # pylint: disable=protected-access

    async def test_constructor_resolves_default_values_for_invalid_inputs(self) -> None:
        client_invalid_port = self._new_client(config=_make_config(host=" ", port="not-int"))
        self.assertEqual(client_invalid_port._host, "127.0.0.1")  # pylint: disable=protected-access
        self.assertEqual(client_invalid_port._port, 2323)  # pylint: disable=protected-access

        client_non_positive = self._new_client(
            config=_make_config(
                port="0",
                read_timeout_seconds=0,
                max_prompt_bytes=0,
            )
        )
        self.assertEqual(client_non_positive._port, 2323)  # pylint: disable=protected-access
        self.assertIsNone(client_non_positive._read_timeout_seconds)  # pylint: disable=protected-access
        self.assertEqual(client_non_positive._max_prompt_bytes, 4096)  # pylint: disable=protected-access

        client_bad_limits = self._new_client(
            config=_make_config(
                read_timeout_seconds="bad",
                max_prompt_bytes="bad",
            )
        )
        self.assertEqual(client_bad_limits._read_timeout_seconds, 300.0)  # pylint: disable=protected-access
        self.assertEqual(client_bad_limits._max_prompt_bytes, 4096)  # pylint: disable=protected-access

    async def test_start_server_without_socket_logs_generic_start(self) -> None:
        client = self._new_client()
        server = _DummyServer(with_socket=False)
        with patch(
            "mugen.devtools.telnet_harness.asyncio.start_server",
            new=AsyncMock(return_value=server),
        ):
            await client.start_server()
        client._logging_gateway.info.assert_called_with("Dev telnet harness started.")  # pylint: disable=protected-access

    async def test_resolve_session_identity_fallback_paths(self) -> None:
        client = self._new_client()
        self.assertEqual(
            client._resolve_session_identity(_DummyWriterNoPeer()),  # pylint: disable=protected-access
            ("telnet_room", "telnet_user"),
        )
        self.assertEqual(
            client._resolve_session_identity(_DummyWriterPeerString()),  # pylint: disable=protected-access
            ("telnet_room", "telnet_user"),
        )

    async def test_write_handles_connection_error(self) -> None:
        client = self._new_client()
        writer = _DummyWriter()
        writer.drain = AsyncMock(side_effect=ConnectionError("closed"))
        success = await client._write(writer, b"x")  # pylint: disable=protected-access
        self.assertFalse(success)
        client._logging_gateway.debug.assert_called_with(  # pylint: disable=protected-access
            "Telnet client disconnected while writing."
        )

    async def test_close_writer_ignores_close_failures(self) -> None:
        client = self._new_client()
        writer = _DummyWriter()
        writer.wait_closed = AsyncMock(side_effect=ConnectionError("close-fail"))
        await client._close_writer(writer)  # pylint: disable=protected-access
        self.assertEqual(writer.close_calls, 1)
        writer.wait_closed.assert_awaited_once()

    async def test_readline_timeout_and_no_timeout_paths(self) -> None:
        client = self._new_client()
        reader = _DummyReader([b"x\n"])
        client._read_timeout_seconds = None  # pylint: disable=protected-access
        self.assertEqual(
            await client._readline(reader),  # pylint: disable=protected-access
            b"x\n",
        )

        async def _raise_timeout(awaitable, timeout):  # noqa: ARG001
            awaitable.close()
            raise asyncio.TimeoutError()

        client._read_timeout_seconds = 1.0  # pylint: disable=protected-access
        with patch("mugen.devtools.telnet_harness.asyncio.wait_for", new=_raise_timeout):
            self.assertIsNone(
                await client._readline(_DummyReader([b"y\n"]))  # pylint: disable=protected-access
            )

    async def test_handle_connection_prompt_write_failure(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(return_value=False)  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access
        client._close_writer.assert_awaited_once()  # pylint: disable=protected-access

    async def test_handle_connection_read_none_breaks(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(return_value=True)  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=None)  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access
        client._close_writer.assert_awaited_once()  # pylint: disable=protected-access

    async def test_handle_connection_handles_disconnect_payload(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(return_value=True)  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=b"")  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access
        client._logging_gateway.debug.assert_any_call("User disconnected from telnet.")  # pylint: disable=protected-access

    async def test_handle_connection_limits_and_payload_branches(self) -> None:
        client = self._new_client()
        client._max_prompt_bytes = 1  # pylint: disable=protected-access
        client._write = AsyncMock(side_effect=[True, True, False])  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=b"abcd\n")  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access
        client._logging_gateway.warning.assert_any_call(  # pylint: disable=protected-access
            "Telnet payload exceeded max prompt size (1 bytes)."
        )

    async def test_handle_connection_unicode_error_branch(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(return_value=True)  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=b"\xff")  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access
        client._logging_gateway.warning.assert_any_call(  # pylint: disable=protected-access
            "Invalid telnet payload encoding. Closing connection."
        )

    async def test_handle_connection_blank_prompt_continues(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(side_effect=[True, False])  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=b"  \n")  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access

    async def test_handle_connection_assistant_write_failure(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(side_effect=[True, False])  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=b"hello\n")  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access

    async def test_handle_connection_no_text_responses(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(side_effect=[True, True, False])  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=b"hello\n")  # pylint: disable=protected-access
        client._handle_text_message = AsyncMock(return_value=[])  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access

    async def test_handle_connection_payload_write_failure(self) -> None:
        client = self._new_client()
        client._write = AsyncMock(side_effect=[True, True, False])  # pylint: disable=protected-access
        client._readline = AsyncMock(return_value=b"hello\n")  # pylint: disable=protected-access
        client._handle_text_message = AsyncMock(return_value=["ok"])  # pylint: disable=protected-access
        client._close_writer = AsyncMock()  # pylint: disable=protected-access
        await client._handle_connection(_DummyReader([]), _DummyWriter())  # pylint: disable=protected-access

    async def test_handle_text_message_filters_non_text_responses(self) -> None:
        client = self._new_client()
        client._messaging_service.handle_text_message = AsyncMock(
            return_value=[
                "not-dict",
                {"type": "image", "content": "skip"},
                {"type": "text", "content": None},
                {"type": "text", "content": "ok"},
            ]
        )
        responses = await client._handle_text_message("hello")  # pylint: disable=protected-access
        self.assertEqual(responses, ["ok"])


class TestRunDevTelnetServer(unittest.IsolatedAsyncioTestCase):
    """Covers dev telnet harness runtime guardrails."""

    async def test_blocks_non_dev_environment(self) -> None:
        with self.assertRaises(RuntimeError):
            await run_dev_telnet_server(
                config_provider=lambda: _make_config(environment="production"),
                logger_provider=lambda: Mock(),
                ipc_provider=lambda: Mock(),
                keyval_provider=lambda: Mock(),
                messaging_provider=lambda: Mock(handle_text_message=AsyncMock(return_value=[])),
                user_provider=lambda: Mock(),
            )

    async def test_starts_in_development_environment(self) -> None:
        started = Mock()

        async def _fake_start_server(self, started_callback=None):
            if callable(started_callback):
                started_callback()

        with patch.object(
            DevTelnetHarnessClient,
            "start_server",
            new=_fake_start_server,
        ):
            await run_dev_telnet_server(
                config_provider=lambda: _make_config(environment="development"),
                logger_provider=lambda: Mock(),
                ipc_provider=lambda: Mock(),
                keyval_provider=lambda: Mock(),
                messaging_provider=lambda: Mock(handle_text_message=AsyncMock(return_value=[])),
                user_provider=lambda: Mock(),
                started_callback=started,
            )
        started.assert_called_once_with()

    async def test_starts_in_testing_environment(self) -> None:
        async def _fake_start_server(self, started_callback=None):
            _ = started_callback

        logger = Mock()
        with patch.object(
            DevTelnetHarnessClient,
            "start_server",
            new=_fake_start_server,
        ):
            await run_dev_telnet_server(
                config_provider=lambda: _make_config(environment="testing"),
                logger_provider=lambda: logger,
                ipc_provider=lambda: Mock(),
                keyval_provider=lambda: Mock(),
                messaging_provider=lambda: Mock(handle_text_message=AsyncMock(return_value=[])),
                user_provider=lambda: Mock(),
            )

    async def test_main_entrypoint_uses_asyncio_run(self) -> None:
        def _consume(awaitable):
            awaitable.close()
            return None

        with patch("mugen.devtools.telnet_harness.asyncio.run", side_effect=_consume) as run_mock:
            harness_mod._main()
        run_mock.assert_called_once()

    async def test_module_main_guard_invokes_main(self) -> None:
        def _consume(awaitable):
            awaitable.close()
            return None

        sys.modules.pop("mugen.devtools.telnet_harness", None)
        with patch("asyncio.run", side_effect=_consume) as run_mock:
            runpy.run_module("mugen.devtools.telnet_harness", run_name="__main__")
        run_mock.assert_called()


if __name__ == "__main__":
    unittest.main()
