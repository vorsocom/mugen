"""Provides unit tests for mugen.run_clients."""

import asyncio
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart

import mugen as mugen_mod
from mugen import (
    PHASE_B_ERROR_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_HEALTHY,
    BootstrapConfigError,
    run_clients,
    run_platform_clients,
)


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

    async def test_web_platform_enabled(self) -> None:
        """Test running web platform."""
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["web"],
            )
        )

        _run_web_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_web_client",
                new=_run_web_client,
            ),
        ):
            await run_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: None,
                web_provider=lambda: None,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running web client.",
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

    async def test_run_platform_clients_marks_phase_b_healthy_on_completion(self) -> None:
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
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

    async def test_run_platform_clients_handles_cancellation(
        self,
    ) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["whatsapp"]))
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
                whatsapp_provider=lambda: None,
            )

    async def test_run_platform_clients_blocks_telnet_in_production(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["telnet"],
                environment="production",
            ),
            telnet=SimpleNamespace(allow_in_production=False),
        )

        with self.assertRaises(BootstrapConfigError):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    def test_telnet_allow_in_production_parsing(self) -> None:
        self.assertTrue(
            mugen_mod._telnet_allowed_in_production(  # pylint: disable=protected-access
                SimpleNamespace(telnet=SimpleNamespace(allow_in_production="yes"))
            )
        )
        self.assertFalse(
            mugen_mod._telnet_allowed_in_production(  # pylint: disable=protected-access
                SimpleNamespace(telnet=SimpleNamespace(allow_in_production="off"))
            )
        )
        self.assertFalse(
            mugen_mod._telnet_allowed_in_production(  # pylint: disable=protected-access
                SimpleNamespace(telnet=SimpleNamespace(allow_in_production=object()))
            )
        )
        self.assertFalse(
            mugen_mod._telnet_allowed_in_production(  # pylint: disable=protected-access
                SimpleNamespace(telnet=SimpleNamespace(allow_in_production="maybe"))
            )
        )

    async def test_run_platform_clients_allows_telnet_with_explicit_override(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["telnet"],
                environment="production",
            ),
            telnet=SimpleNamespace(allow_in_production=True),
        )
        _run_telnet_client = unittest.mock.AsyncMock()

        with unittest.mock.patch(
            target="mugen.run_telnet_client",
            new=_run_telnet_client,
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
        _run_telnet_client.assert_awaited_once()

    def test_whatsapp_provider_reads_di_container(self) -> None:
        sentinel_client = object()
        with unittest.mock.patch.object(
            mugen_mod.di,
            "container",
            SimpleNamespace(whatsapp_client=sentinel_client),
        ):
            self.assertIs(
                mugen_mod._whatsapp_provider(),  # pylint: disable=protected-access
                sentinel_client,
            )
