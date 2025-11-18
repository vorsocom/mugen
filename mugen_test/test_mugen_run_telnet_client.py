"""Provides unit tests for mugen.run_telnet_client."""

import asyncio
from types import TracebackType
import unittest

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

            async def start_server(self) -> None:
                """Start Telnet server."""

        with (self.assertLogs(logger="test_app", level="DEBUG") as logger,):
            await run_telnet_client(
                logger=app.logger, telnet_client=DummyTelnetClient()
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

            async def start_server(self) -> None:
                """Start Telnet server."""
                raise asyncio.exceptions.CancelledError

        with (self.assertLogs(logger="test_app", level="DEBUG") as logger,):
            await run_telnet_client(
                logger=app.logger, telnet_client=DummyTelnetClient()
            )
            self.assertEqual(
                logger.output[0],
                "ERROR:test_app:Telnet client shutting down.",
            )
