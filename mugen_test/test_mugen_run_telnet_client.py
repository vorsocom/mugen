"""Provides unit tests for mugen.run_telnet_client."""

import asyncio
from types import TracebackType
import unittest
from unittest.mock import Mock

from quart import Quart

from mugen import run_telnet_client
from mugen.core.contract.client.telnet import ITelnetClient


class TestMuGenInitRunTelnetClient(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_telnet_client."""

    async def test_normal_run(self) -> None:
        """Test normal run of telnet client."""
        # Create dummy app to get context.
        app = Quart("test_app")

        class DummyTelnetClient(ITelnetClient):
            """Dummy telnet client."""

            async def __aenter__(self) -> None:
                """Initialisation routine."""
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                """Finalisation routine."""

            async def start_server(self, started_callback=None) -> None:
                """Start Telnet server."""
                if callable(started_callback):
                    started_callback()

        with (self.assertLogs(logger="test_app", level="DEBUG") as logger,):
            await run_telnet_client(
                logger_provider=lambda: app.logger,
                telnet_provider=DummyTelnetClient,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Telnet client started.",
            )

    async def test_cancelled_error(self) -> None:
        """Test effects of asyncio.exceptions.CancelledError."""
        # Create dummy app to get context.
        app = Quart("test_app")

        class DummyTelnetClient(ITelnetClient):
            """Dummy telnet client."""

            async def __aenter__(self) -> None:
                """Initialisation routine."""
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                """Finalisation routine."""

            async def start_server(self, started_callback=None) -> None:
                """Start Telnet server."""
                raise asyncio.exceptions.CancelledError

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            self.assertRaises(asyncio.exceptions.CancelledError),
        ):
            await run_telnet_client(
                logger_provider=lambda: app.logger,
                telnet_provider=DummyTelnetClient,
            )
        self.assertEqual(
            logger.output[0],
            "ERROR:test_app:Telnet client shutting down.",
        )

    async def test_started_callback_is_invoked(self) -> None:
        app = Quart("test_app")

        class DummyTelnetClient(ITelnetClient):
            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

            async def start_server(self, started_callback=None) -> None:
                if callable(started_callback):
                    started_callback()

        started = Mock()
        await run_telnet_client(
            logger_provider=lambda: app.logger,
            telnet_provider=DummyTelnetClient,
            started_callback=started,
        )
        started.assert_called_once_with()

    async def test_started_callback_is_not_invoked_until_client_reports_started(self) -> None:
        app = Quart("test_app")
        started = Mock()

        class DummyTelnetClient(ITelnetClient):
            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

            async def start_server(self, started_callback=None) -> None:
                if started.called:
                    raise AssertionError("started callback fired before server startup")
                await asyncio.sleep(0)
                if started.called:
                    raise AssertionError("started callback fired before server startup")
                if callable(started_callback):
                    started_callback()

        await run_telnet_client(
            logger_provider=lambda: app.logger,
            telnet_provider=DummyTelnetClient,
            started_callback=started,
        )
        started.assert_called_once_with()
