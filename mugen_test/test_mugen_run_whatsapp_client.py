"""Provides unit tests for mugen.run_whatspp_client."""

import unittest

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
            await run_whatsapp_client(
                logger=app.logger, whatsapp_client=DummyWhatsAppClient()
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:WhatsApp client started.",
            )
