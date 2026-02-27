"""Provides unit tests for mugen.run_whatspp_client."""

import asyncio
import unittest
from unittest.mock import Mock

from quart import Quart

from mugen import run_whatsapp_client


class TestMuGenInitRunTelnetClient(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_telnet_client."""

    async def test_normal_run(self) -> None:
        """Test normal run of telnet client."""
        # Create dummy app to get context.
        app = Quart("test_app")

        class DummyWhatsAppClient:
            """Dummy whatsapp client."""

            async def init(self) -> None:
                """Perform startup routine."""

            async def close(self) -> None:
                """Perform shutdown routine."""

        with (self.assertLogs(logger="test_app", level="DEBUG") as logger,):
            task = asyncio.create_task(
                run_whatsapp_client(
                    logger_provider=lambda: app.logger,
                    whatsapp_provider=DummyWhatsAppClient,
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:WhatsApp client started.",
            )
            self.assertEqual(
                logger.output[1],
                "DEBUG:test_app:WhatsApp client shutting down.",
            )

    async def test_close_error_is_logged(self) -> None:
        app = Quart("test_app")

        class DummyWhatsAppClient:
            async def init(self) -> None:
                ...

            async def close(self) -> None:
                raise RuntimeError("boom")

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            task = asyncio.create_task(
                run_whatsapp_client(
                    logger_provider=lambda: app.logger,
                    whatsapp_provider=DummyWhatsAppClient,
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.assertTrue(
            any("Failed to close whatsapp client (boom)." in msg for msg in logger.output)
        )

    async def test_started_callback_is_invoked(self) -> None:
        app = Quart("test_app")
        started = Mock()

        class DummyWhatsAppClient:
            async def init(self) -> None:
                ...

            async def close(self) -> None:
                ...

        task = asyncio.create_task(
            run_whatsapp_client(
                logger_provider=lambda: app.logger,
                whatsapp_provider=DummyWhatsAppClient,
                started_callback=started,
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        started.assert_called_once_with()
