"""Provides unit tests for mugen.run_web_client."""

import asyncio
import unittest
from unittest.mock import Mock

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

            async def wait_until_stopped(self) -> None:
                """Block until runtime exits."""

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await run_web_client(
                logger_provider=lambda: app.logger,
                web_provider=DummyWebClient,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Web client started.",
            )

    async def test_cancelled_run_logs_shutdown_and_close_warning(self) -> None:
        app = Quart("test_app")

        class DummyWebClient:
            def __init__(self) -> None:
                self._block = asyncio.Event()

            async def init(self) -> None:
                ...

            async def close(self) -> None:
                raise RuntimeError("boom")

            async def wait_until_stopped(self) -> None:
                await self._block.wait()

        client = DummyWebClient()

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            task = asyncio.create_task(
                run_web_client(
                    logger_provider=lambda: app.logger,
                    web_provider=lambda: client,
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.assertTrue(any("Web client shutting down." in msg for msg in logger.output))
        self.assertTrue(any("Failed to close web client (boom)." in msg for msg in logger.output))

    async def test_started_callback_is_invoked(self) -> None:
        app = Quart("test_app")
        started = Mock()
        healthy = Mock()

        class DummyWebClient:
            async def init(self) -> None:
                ...

            async def close(self) -> None:
                ...

            async def wait_until_stopped(self) -> None:
                await asyncio.Event().wait()

        task = asyncio.create_task(
            run_web_client(
                logger_provider=lambda: app.logger,
                web_provider=DummyWebClient,
                started_callback=started,
                healthy_callback=healthy,
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        started.assert_called_once_with()
        healthy.assert_called_once_with()

    async def test_degraded_callback_is_invoked_when_init_fails(self) -> None:
        app = Quart("test_app")
        degraded = Mock()

        class DummyWebClient:
            async def init(self) -> None:
                raise RuntimeError("init failed")

            async def close(self) -> None:
                ...

            async def wait_until_stopped(self) -> None:
                ...

        with self.assertRaises(RuntimeError):
            await run_web_client(
                logger_provider=lambda: app.logger,
                web_provider=DummyWebClient,
                degraded_callback=degraded,
            )

        degraded.assert_called_once_with("RuntimeError: init failed")

    async def test_degraded_callback_is_invoked_when_wait_fails(self) -> None:
        app = Quart("test_app")
        degraded = Mock()

        class DummyWebClient:
            async def init(self) -> None:
                ...

            async def close(self) -> None:
                ...

            async def wait_until_stopped(self) -> None:
                raise RuntimeError("wait failed")

        with self.assertRaises(RuntimeError):
            await run_web_client(
                logger_provider=lambda: app.logger,
                web_provider=DummyWebClient,
                degraded_callback=degraded,
            )

        degraded.assert_called_once_with("RuntimeError: wait failed")

    async def test_init_failure_without_degraded_callback_still_raises(self) -> None:
        app = Quart("test_app")

        class DummyWebClient:
            async def init(self) -> None:
                raise RuntimeError("init failed")

            async def close(self) -> None:
                ...

            async def wait_until_stopped(self) -> None:
                ...

        with self.assertRaises(RuntimeError):
            await run_web_client(
                logger_provider=lambda: app.logger,
                web_provider=DummyWebClient,
            )

    async def test_wait_failure_without_degraded_callback_still_raises(self) -> None:
        app = Quart("test_app")

        class DummyWebClient:
            async def init(self) -> None:
                ...

            async def close(self) -> None:
                ...

            async def wait_until_stopped(self) -> None:
                raise RuntimeError("wait failed")

        with self.assertRaises(RuntimeError):
            await run_web_client(
                logger_provider=lambda: app.logger,
                web_provider=DummyWebClient,
            )

    async def test_degraded_callback_is_invoked_when_wait_returns(self) -> None:
        app = Quart("test_app")
        degraded = Mock()

        class DummyWebClient:
            async def init(self) -> None:
                ...

            async def close(self) -> None:
                ...

            async def wait_until_stopped(self) -> None:
                return None

        await run_web_client(
            logger_provider=lambda: app.logger,
            web_provider=DummyWebClient,
            degraded_callback=degraded,
        )

        degraded.assert_called_once_with("Web client stopped.")
