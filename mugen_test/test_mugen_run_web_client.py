"""Provides unit tests for mugen.run_web_client."""

import unittest

from quart import Quart

from mugen import run_web_client


class TestMuGenInitRunWebClient(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_web_client."""

    async def test_normal_run(self) -> None:
        """Test normal run of web client."""
        app = Quart("test_app")

        class DummyWebClient:
            """Dummy web client."""

            async def init(self) -> None:
                """Perform startup routine."""

            async def close(self) -> None:
                """Perform shutdown routine."""

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await run_web_client(
                logger_provider=lambda: app.logger,
                web_provider=DummyWebClient,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Web client started.",
            )
