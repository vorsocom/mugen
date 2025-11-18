"""Provides unit tests for mugen.run_clients."""

import asyncio
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart

from mugen import run_clients


class TestMuGenInitRunClients(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_clients."""

    async def test_platforms_configuration_unavailable(self) -> None:
        """Test effects of missing platforms configuration."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(mugen=SimpleNamespace())

        with (
            self.assertLogs(logger="test_app", level="ERROR"),
            self.assertRaises(SystemExit),
        ):
            await run_clients(app, config=config, logger=app.logger)

    async def test_matrix_platform_enabled(self) -> None:
        """Test running matrix platform."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["matrix"],
            )
        )

        _run_matrix_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_matrix_client", new=_run_matrix_client
            ),
        ):
            await run_clients(app, config=config, logger=app.logger)
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running matrix client.",
            )

    async def test_telnet_platform_enabled(self) -> None:
        """Test running telnet platform."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["telnet"],
            )
        )

        _run_telnet_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_telnet_client", new=_run_telnet_client
            ),
        ):
            await run_clients(app, config=config, logger=app.logger)
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running telnet client.",
            )

    async def test_whatsapp_platform_enabled(self) -> None:
        """Test running whatsapp platform."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["whatsapp"],
            )
        )

        _run_whatsapp_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_whatsapp_client", new=_run_whatsapp_client
            ),
        ):
            await run_clients(app, config=config, logger=app.logger)
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running whatsapp client.",
            )

    async def test_cancelled_error_exception_client_none(self) -> None:
        """Test throwing CancelledError exception when WhatsApp client is not set."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["whatsapp"],
            )
        )

        _run_whatsapp_client = unittest.mock.AsyncMock(
            side_effect=asyncio.exceptions.CancelledError
        )

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_whatsapp_client", new=_run_whatsapp_client
            ),
        ):
            await run_clients(
                app, config=config, logger=app.logger, whatsapp_client=None
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running whatsapp client.",
            )

    async def test_cancelled_error_exception(self) -> None:
        """Test throwing CancelledError exception."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["whatsapp"],
            )
        )

        _run_whatsapp_client = unittest.mock.AsyncMock(
            side_effect=asyncio.exceptions.CancelledError
        )

        # Dummy subclasses
        # pylint: disable=too-few-public-methods
        class DummyWhatsAppClientClass:
            """Dummy WhatsApp client class."""

            async def close(self):
                """..."""

        whatsapp_client = DummyWhatsAppClientClass()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_whatsapp_client", new=_run_whatsapp_client
            ),
        ):
            await run_clients(
                app, config=config, logger=app.logger, whatsapp_client=whatsapp_client
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running whatsapp client.",
            )
            self.assertEqual(
                logger.output[1],
                "DEBUG:test_app:Closing whatsapp client.",
            )
