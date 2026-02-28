"""Provides unit tests for mugen.run_matrix_client."""

import asyncio
from types import SimpleNamespace, TracebackType
from typing import Type
import unittest
import unittest.mock

from quart import Quart

import mugen as mugen_mod
from mugen import run_matrix_client


def _sync_signal(wait_side_effect=None) -> SimpleNamespace:
    wait_kwargs = {}
    if wait_side_effect is not None:
        wait_kwargs["side_effect"] = wait_side_effect
    return SimpleNamespace(
        wait=unittest.mock.AsyncMock(**wait_kwargs),
        clear=unittest.mock.Mock(),
    )


class TestMuGenInitRunMatrixClient(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_matrix_client."""

    async def test_normal_run(self) -> None:
        """Test normal run of matrix client."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClientNormal:
            """Dummy matrix client."""

            synced = _sync_signal()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock()
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                """Initialisation routine."""
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                """Finalisation routine."""

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClientNormal,
            )
            self.assertEqual(logger.output[0], "DEBUG:test_app:Matrix client started.")

    async def test_normal_run_matching_displayname(self) -> None:
        """Test normal run of matrix client when current and proposed display
        names match.
        """
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClientNormal:
            """Dummy matrix client."""

            synced = _sync_signal()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock()
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                """Initialisation routine."""
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                """Finalisation routine."""

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClientNormal,
            )
            self.assertEqual(logger.output[0], "DEBUG:test_app:Matrix client started.")

    async def test_started_callback_is_invoked_after_first_sync(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )
        started = unittest.mock.Mock()

        class DummyMatrixClient:
            synced = _sync_signal()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(return_value=None)
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        await run_matrix_client(
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
            matrix_provider=DummyMatrixClient,
            started_callback=started,
        )
        started.assert_called_once_with()

    async def test_sync_signal_clear_awaitable_is_awaited(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )
        clear_mock = unittest.mock.AsyncMock()

        class DummyMatrixClient:
            synced = SimpleNamespace(
                wait=unittest.mock.AsyncMock(),
                clear=clear_mock,
            )
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(return_value=None)
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        await run_matrix_client(
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
            matrix_provider=DummyMatrixClient,
        )
        clear_mock.assert_awaited_once_with()

    async def test_sync_signal_without_clear_is_supported(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClient:
            synced = SimpleNamespace(wait=unittest.mock.AsyncMock())
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(return_value=None)
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        await run_matrix_client(
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
            matrix_provider=DummyMatrixClient,
        )

    async def test_cancelled_error(self) -> None:
        """Test effects of asyncio.exceptions.CancelledError."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClient:
            """Dummy matrix client."""

            synced = _sync_signal()
            profile = unittest.mock.Mock()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(
                side_effect=asyncio.exceptions.CancelledError
            )
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                """Initialisation routine."""
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                """Finalisation routine."""

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            self.assertRaises(asyncio.exceptions.CancelledError),
        ):
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClient,
            )
        self.assertEqual(
            logger.output[0], "ERROR:test_app:Matrix client shutting down."
        )

    async def test_sync_transient_error_retries_and_recovers(self) -> None:
        """Retry after transient sync failure and recover."""
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClient:
            synced = _sync_signal()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(
                side_effect=[RuntimeError("temporary sync error"), None]
            )
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        with (
            unittest.mock.patch.object(mugen_mod.random, "uniform", return_value=0.0),
            unittest.mock.patch.object(
                mugen_mod.asyncio,
                "sleep",
                new=unittest.mock.AsyncMock(),
            ) as sleep_mock,
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
        ):
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClient,
            )

        self.assertEqual(DummyMatrixClient.sync_forever.await_count, 2)
        sleep_mock.assert_awaited_once_with(1.0)
        self.assertTrue(any("retrying." in line for line in logger.output))
        self.assertTrue(any("Matrix client started." in line for line in logger.output))

    async def test_sync_transient_error_emits_runtime_health_callbacks(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )
        degraded = unittest.mock.Mock()
        healthy = unittest.mock.Mock()

        class DummyMatrixClient:
            synced = _sync_signal()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(
                side_effect=[RuntimeError("temporary sync error"), None]
            )
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        with (
            unittest.mock.patch.object(mugen_mod.random, "uniform", return_value=0.0),
            unittest.mock.patch.object(
                mugen_mod.asyncio,
                "sleep",
                new=unittest.mock.AsyncMock(),
            ),
        ):
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClient,
                degraded_callback=degraded,
                healthy_callback=healthy,
            )

        degraded.assert_called_once_with("RuntimeError: temporary sync error")
        self.assertGreaterEqual(healthy.call_count, 1)

    async def test_sync_transient_failures_before_sync_emit_degraded_once(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )
        degraded = unittest.mock.Mock()

        async def _wait_never() -> None:
            await asyncio.Future()

        class DummyMatrixClient:
            synced = _sync_signal(wait_side_effect=_wait_never)
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(side_effect=RuntimeError("network"))
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        with (
            unittest.mock.patch.object(mugen_mod.random, "uniform", return_value=0.0),
            unittest.mock.patch.object(
                mugen_mod.asyncio,
                "sleep",
                new=unittest.mock.AsyncMock(),
            ),
            self.assertRaises(RuntimeError),
        ):
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClient,
                degraded_callback=degraded,
            )

        degraded.assert_called_once_with("RuntimeError: network")

    async def test_sync_recovery_resets_retry_budget(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClient:
            synced = _sync_signal()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(
                side_effect=[
                    RuntimeError("network"),
                    RuntimeError("network"),
                    RuntimeError("network"),
                    RuntimeError("network"),
                    RuntimeError("network"),
                    RuntimeError("network"),
                    None,
                ]
            )
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        with (
            unittest.mock.patch.object(mugen_mod.random, "uniform", return_value=0.0),
            unittest.mock.patch.object(
                mugen_mod.asyncio,
                "sleep",
                new=unittest.mock.AsyncMock(),
            ) as sleep_mock,
        ):
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClient,
            )

        self.assertEqual(DummyMatrixClient.sync_forever.await_count, 7)
        self.assertEqual(sleep_mock.await_count, 6)

    async def test_sync_authentication_failure_stops_without_retry(self) -> None:
        """Auth-like sync failures should shut down immediately."""
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )

        class DummyMatrixClient:
            synced = _sync_signal()
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(
                side_effect=RuntimeError("M_UNKNOWN_TOKEN")
            )
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        with (
            unittest.mock.patch.object(
                mugen_mod.asyncio,
                "sleep",
                new=unittest.mock.AsyncMock(),
            ) as sleep_mock,
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            self.assertRaises(RuntimeError),
        ):
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClient,
            )

        self.assertEqual(DummyMatrixClient.sync_forever.await_count, 1)
        sleep_mock.assert_not_awaited()
        self.assertTrue(
            any(
                "Matrix client authentication failed; shutting down." in line
                for line in logger.output
            )
        )

    async def test_sync_failure_stops_after_retry_budget(self) -> None:
        """Repeated transient failures should stop after max retries."""
        app = Quart("test_app")
        config = SimpleNamespace(
            matrix=SimpleNamespace(
                assistant=SimpleNamespace(
                    name="Test Agent",
                )
            )
        )
        wait_call_count = 0

        async def _wait_once_then_block() -> None:
            nonlocal wait_call_count
            wait_call_count += 1
            if wait_call_count == 1:
                return
            await asyncio.Future()

        class DummyMatrixClient:
            synced = _sync_signal(wait_side_effect=_wait_once_then_block)
            get_profile = unittest.mock.AsyncMock()
            get_profile.return_value = SimpleNamespace(displayname="Test Agent")
            set_displayname = unittest.mock.AsyncMock()
            sync_forever = unittest.mock.AsyncMock(side_effect=RuntimeError("network"))
            sync_token = unittest.mock.MagicMock()
            trust_known_user_devices = unittest.mock.AsyncMock()

            async def __aenter__(self) -> None:
                return self

            async def __aexit__(
                self,
                exc_type: Type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None,
            ) -> bool:
                return False

        with (
            unittest.mock.patch.object(mugen_mod.random, "uniform", return_value=0.0),
            unittest.mock.patch.object(
                mugen_mod.asyncio,
                "sleep",
                new=unittest.mock.AsyncMock(),
            ) as sleep_mock,
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            self.assertRaises(RuntimeError),
        ):
            await run_matrix_client(
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                matrix_provider=DummyMatrixClient,
            )

        self.assertEqual(DummyMatrixClient.sync_forever.await_count, 6)
        self.assertEqual(sleep_mock.await_count, 5)
        self.assertTrue(
            any(
                "Matrix client sync failed after max retries." in line
                for line in logger.output
            )
        )
