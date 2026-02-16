"""Provides unit tests for mugen.run_clients."""

import asyncio
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart

from mugen import BootstrapConfigError, run_clients, run_platform_clients


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
            self.assertRaises(BootstrapConfigError),
        ):
            await run_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

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
            await run_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
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
            await run_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
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
            await run_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
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
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: None,
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
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: whatsapp_client,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running whatsapp client.",
            )
            self.assertEqual(
                logger.output[1],
                "DEBUG:test_app:Closing whatsapp client.",
            )

    async def test_run_platform_clients_closes_keyval_on_completion(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["matrix"]))
        keyval_storage_gateway = unittest.mock.Mock()
        _run_matrix_client = unittest.mock.AsyncMock()

        with unittest.mock.patch(
            target="mugen.run_matrix_client",
            new=_run_matrix_client,
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: None,
                keyval_storage_gateway_provider=lambda: keyval_storage_gateway,
            )

        keyval_storage_gateway.close.assert_called_once_with()

    async def test_run_platform_clients_closes_keyval_gateway_on_cancellation(
        self,
    ) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["whatsapp"]))
        keyval_storage_gateway = unittest.mock.Mock()
        whatsapp_client = unittest.mock.Mock()
        whatsapp_client.close = unittest.mock.AsyncMock()
        _run_whatsapp_client = unittest.mock.AsyncMock(
            side_effect=asyncio.exceptions.CancelledError
        )

        with unittest.mock.patch(
            target="mugen.run_whatsapp_client",
            new=_run_whatsapp_client,
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: whatsapp_client,
                keyval_storage_gateway_provider=lambda: keyval_storage_gateway,
            )

        whatsapp_client.close.assert_awaited_once()
        keyval_storage_gateway.close.assert_called_once_with()

    async def test_run_platform_clients_warns_when_whatsapp_close_fails(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["whatsapp"]))
        keyval_storage_gateway = unittest.mock.Mock()
        whatsapp_client = unittest.mock.Mock()
        whatsapp_client.close = unittest.mock.AsyncMock(
            side_effect=RuntimeError("boom")
        )
        _run_whatsapp_client = unittest.mock.AsyncMock(
            side_effect=asyncio.exceptions.CancelledError
        )

        with (
            self.assertLogs(logger="test_app", level="WARNING") as logs,
            unittest.mock.patch(
                target="mugen.run_whatsapp_client",
                new=_run_whatsapp_client,
            ),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: whatsapp_client,
                keyval_storage_gateway_provider=lambda: keyval_storage_gateway,
            )

        self.assertTrue(
            any(
                "Failed to close whatsapp client (boom)." in entry
                for entry in logs.output
            )
        )

    async def test_run_platform_clients_warns_when_keyval_close_fails(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["matrix"]))
        keyval_storage_gateway = unittest.mock.Mock()
        keyval_storage_gateway.close = unittest.mock.Mock(
            side_effect=RuntimeError("kv boom")
        )
        _run_matrix_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="WARNING") as logs,
            unittest.mock.patch(
                target="mugen.run_matrix_client",
                new=_run_matrix_client,
            ),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: None,
                keyval_storage_gateway_provider=lambda: keyval_storage_gateway,
            )

        self.assertTrue(
            any(
                "Failed to close keyval storage gateway (kv boom)." in entry
                for entry in logs.output
            )
        )

    async def test_run_platform_clients_handles_absent_keyval_gateway(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["matrix"]))
        _run_matrix_client = unittest.mock.AsyncMock()

        with unittest.mock.patch(
            target="mugen.run_matrix_client",
            new=_run_matrix_client,
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: None,
                keyval_storage_gateway_provider=lambda: None,
            )
