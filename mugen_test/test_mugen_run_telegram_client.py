"""Provides unit tests for mugen.run_telegram_client."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from quart import Quart

from mugen import run_telegram_client


class TestMuGenInitRunTelegramClient(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_telegram_client."""

    async def test_normal_run(self) -> None:
        app = Quart("test_app")

        class DummyTelegramClient:
            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                ...

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            task = asyncio.create_task(
                run_telegram_client(
                    logger_provider=lambda: app.logger,
                    telegram_provider=DummyTelegramClient,
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Telegram client started.",
            )
            self.assertEqual(
                logger.output[1],
                "DEBUG:test_app:Telegram client shutting down.",
            )

    async def test_close_error_is_logged(self) -> None:
        app = Quart("test_app")

        class DummyTelegramClient:
            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                raise RuntimeError("boom")

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            task = asyncio.create_task(
                run_telegram_client(
                    logger_provider=lambda: app.logger,
                    telegram_provider=DummyTelegramClient,
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            results = await asyncio.gather(task, return_exceptions=True)

        self.assertTrue(
            any("Telegram client shutdown failed" in msg for msg in logger.output)
        )
        self.assertTrue(
            any(
                isinstance(result, RuntimeError)
                and "shutdown failed during cancellation" in str(result)
                for result in results
            )
        )

    async def test_close_error_is_raised_when_runtime_has_no_primary_error(
        self,
    ) -> None:
        app = Quart("test_app")

        class DummyTelegramClient:
            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                raise RuntimeError("close failed")

        with (
            unittest.mock.patch(
                "mugen.asyncio.sleep",
                new=AsyncMock(side_effect=SystemExit("stop")),
            ),
            self.assertRaisesRegex(RuntimeError, "close failed"),
        ):
            await run_telegram_client(
                logger_provider=lambda: app.logger,
                telegram_provider=DummyTelegramClient,
            )

    async def test_started_callback_is_invoked(self) -> None:
        app = Quart("test_app")
        started = Mock()

        class DummyTelegramClient:
            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                ...

        task = asyncio.create_task(
            run_telegram_client(
                logger_provider=lambda: app.logger,
                telegram_provider=DummyTelegramClient,
                started_callback=started,
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        started.assert_called_once_with()

    async def test_probe_failure_does_not_invoke_started_callback(self) -> None:
        app = Quart("test_app")
        started = Mock()
        closed = AsyncMock()

        class DummyTelegramClient:
            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                return False

            async def close(self) -> None:
                await closed()

        with self.assertRaises(RuntimeError):
            await run_telegram_client(
                logger_provider=lambda: app.logger,
                telegram_provider=DummyTelegramClient,
                started_callback=started,
            )

        started.assert_not_called()
        closed.assert_awaited_once()

    async def test_runtime_probe_degrades_and_recovers_with_callbacks(self) -> None:
        app = Quart("test_app")
        degraded = Mock()
        healthy = Mock()
        closed = AsyncMock()
        degraded_event = asyncio.Event()
        recovered_event = asyncio.Event()

        class DummyTelegramClient:
            def __init__(self) -> None:
                self._probe_calls = 0

            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                self._probe_calls += 1
                if self._probe_calls == 1:
                    return True
                if self._probe_calls == 2:
                    return False
                if self._probe_calls == 3:
                    return True
                await asyncio.Event().wait()
                return True

            async def close(self) -> None:
                await closed()

        with unittest.mock.patch(
            "mugen.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ):

            def _on_degraded(reason: str) -> None:
                degraded(reason)
                degraded_event.set()

            def _on_healthy() -> None:
                healthy()
                if healthy.call_count >= 2:
                    recovered_event.set()

            task = asyncio.create_task(
                run_telegram_client(
                    logger_provider=lambda: app.logger,
                    telegram_provider=DummyTelegramClient,
                    degraded_callback=_on_degraded,
                    healthy_callback=_on_healthy,
                )
            )
            await asyncio.wait_for(degraded_event.wait(), timeout=1.0)
            await asyncio.wait_for(recovered_event.wait(), timeout=1.0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        degraded.assert_called_once_with("Telegram runtime startup probe failed.")
        self.assertEqual(healthy.call_count, 2)
        closed.assert_awaited_once()

    async def test_runtime_probe_exception_emits_degraded_callback(self) -> None:
        app = Quart("test_app")
        degraded = Mock()
        closed = AsyncMock()
        degraded_event = asyncio.Event()

        class DummyTelegramClient:
            def __init__(self) -> None:
                self._probe_calls = 0

            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                self._probe_calls += 1
                if self._probe_calls == 1:
                    return True
                if self._probe_calls == 2:
                    raise RuntimeError("network down")
                if self._probe_calls == 3:
                    raise RuntimeError("network down")
                await asyncio.Event().wait()
                return True

            async def close(self) -> None:
                await closed()

        with unittest.mock.patch(
            "mugen.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ):

            def _on_degraded(reason: str) -> None:
                degraded(reason)
                degraded_event.set()

            task = asyncio.create_task(
                run_telegram_client(
                    logger_provider=lambda: app.logger,
                    telegram_provider=DummyTelegramClient,
                    degraded_callback=_on_degraded,
                )
            )
            await asyncio.wait_for(degraded_event.wait(), timeout=1.0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        degraded.assert_called_once_with("RuntimeError: network down")
        closed.assert_awaited_once()

    async def test_runtime_probe_repeated_unhealthy_emits_single_degraded_callback(self) -> None:
        app = Quart("test_app")
        degraded = Mock()
        closed = AsyncMock()
        repeated_unhealthy_seen = asyncio.Event()

        class DummyTelegramClient:
            def __init__(self) -> None:
                self._probe_calls = 0

            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                self._probe_calls += 1
                if self._probe_calls == 1:
                    return True
                if self._probe_calls == 2:
                    return False
                if self._probe_calls == 3:
                    repeated_unhealthy_seen.set()
                    return False
                await asyncio.Event().wait()
                return True

            async def close(self) -> None:
                await closed()

        with unittest.mock.patch(
            "mugen.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ):
            task = asyncio.create_task(
                run_telegram_client(
                    logger_provider=lambda: app.logger,
                    telegram_provider=DummyTelegramClient,
                    degraded_callback=degraded,
                )
            )
            await asyncio.wait_for(repeated_unhealthy_seen.wait(), timeout=1.0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        degraded.assert_called_once_with("Telegram runtime startup probe failed.")
        closed.assert_awaited_once()

    async def test_startup_exception_invokes_degraded_callback(self) -> None:
        app = Quart("test_app")
        degraded = Mock()
        closed = AsyncMock()

        class DummyTelegramClient:
            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                raise RuntimeError("startup-failed")

            async def close(self) -> None:
                await closed()

        with self.assertRaisesRegex(RuntimeError, "startup-failed"):
            await run_telegram_client(
                logger_provider=lambda: app.logger,
                telegram_provider=DummyTelegramClient,
                degraded_callback=degraded,
            )

        degraded.assert_called_once_with("RuntimeError: startup-failed")
        closed.assert_awaited_once()

    async def test_runtime_recovery_without_healthy_callback_hits_non_callable_branch(self) -> None:
        app = Quart("test_app")
        degraded = Mock()
        recovered_event = asyncio.Event()
        closed = AsyncMock()

        class DummyTelegramClient:
            def __init__(self) -> None:
                self._probe_calls = 0

            async def init(self) -> None:
                ...

            async def verify_startup(self) -> bool:
                self._probe_calls += 1
                if self._probe_calls == 1:
                    return True
                if self._probe_calls == 2:
                    return False
                if self._probe_calls == 3:
                    recovered_event.set()
                    return True
                await asyncio.Event().wait()
                return True

            async def close(self) -> None:
                await closed()

        with unittest.mock.patch(
            "mugen.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ):
            task = asyncio.create_task(
                run_telegram_client(
                    logger_provider=lambda: app.logger,
                    telegram_provider=DummyTelegramClient,
                    degraded_callback=degraded,
                )
            )
            await asyncio.wait_for(recovered_event.wait(), timeout=1.0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        degraded.assert_called_once_with("Telegram runtime startup probe failed.")
        closed.assert_awaited_once()
