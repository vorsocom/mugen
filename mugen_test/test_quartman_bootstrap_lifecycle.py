"""Lifecycle tests for quartman bootstrap sequencing and shutdown behavior."""

import asyncio
from importlib import import_module
import sys
import unittest
import unittest.mock

from quart import Quart

from mugen import (
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_PLATFORM_TASKS_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STOPPED,
    SHUTDOWN_REQUESTED_KEY,
    BootstrapConfigError,
    ExtensionLoadError,
)
from mugen.core.runtime.phase_b_controls import (
    resolve_phase_b_runtime_controls,
    resolve_phase_b_startup_timeout_seconds,
)
from mugen.core.runtime.phase_b_shutdown import PhaseBShutdownError


def _import_quartman_with_app(app: Quart):
    sys.modules.pop("quartman", None)
    with unittest.mock.patch("mugen.create_quart_app", return_value=app):
        return import_module("quartman")


def _runtime_mock(*, startup_timeout_seconds: float) -> unittest.mock.Mock:
    return unittest.mock.Mock(
        profile="platform_full",
        provider_readiness_timeout_seconds=15.0,
        phase_b=unittest.mock.Mock(startup_timeout_seconds=startup_timeout_seconds),
        provider_shutdown_timeout_seconds=10.0,
        shutdown_timeout_seconds=60.0,
    )


class TestQuartmanBootstrapLifecycle(unittest.IsolatedAsyncioTestCase):
    """Validate startup/shutdown sequencing in quartman."""

    async def test_import_logs_and_reraises_bootstrap_creation_failure(self) -> None:
        sys.modules.pop("quartman", None)
        with (
            unittest.mock.patch(
                "mugen.create_quart_app",
                side_effect=BootstrapConfigError("bad config"),
            ),
            self.assertRaises(BootstrapConfigError),
        ):
            import_module("quartman")

    async def test_phase_b_starts_after_phase_a_completes(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        phase_a_entered = asyncio.Event()
        release_phase_a = asyncio.Event()

        async def _blocking_bootstrap(_app: Quart) -> None:
            phase_a_entered.set()
            await release_phase_a.wait()

        phase_b_runner = unittest.mock.AsyncMock()
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=[],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            )
        )

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                container,
            ),
            unittest.mock.patch.object(quartman, "bootstrap_app", new=_blocking_bootstrap),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=phase_b_runner,
            ),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(),
            ),
        ):
            startup_task = asyncio.create_task(quartman.app.startup())

            await asyncio.wait_for(phase_a_entered.wait(), timeout=1.0)
            await asyncio.sleep(0)
            self.assertEqual(phase_b_runner.await_count, 0)

            release_phase_a.set()
            await startup_task
            await asyncio.sleep(0)
            self.assertEqual(phase_b_runner.await_count, 1)

            await quartman.app.shutdown()

    async def test_phase_a_failure_blocks_phase_b(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        phase_b_runner = unittest.mock.AsyncMock()

        with (
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(
                    side_effect=ExtensionLoadError("extension bootstrap failed")
                ),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=phase_b_runner,
            ),
            self.assertRaises(ExtensionLoadError),
        ):
            await quartman.app.startup()

        self.assertEqual(phase_b_runner.await_count, 0)
        await quartman.app.shutdown()

    async def test_phase_a_failure_preserves_existing_non_empty_error(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        async def _bootstrap_then_fail(_app: Quart) -> None:
            state = quartman._bootstrap_state()
            state[quartman.PHASE_A_ERROR_KEY] = "pre-existing phase_a error"
            raise ExtensionLoadError("phase_a failed")

        phase_b_runner = unittest.mock.AsyncMock()

        with (
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=_bootstrap_then_fail,
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=phase_b_runner,
            ),
            self.assertRaises(ExtensionLoadError),
        ):
            await quartman.app.startup()

        state = quartman._bootstrap_state()
        self.assertEqual(state[quartman.PHASE_A_STATUS_KEY], quartman.PHASE_STATUS_DEGRADED)
        self.assertEqual(state[quartman.PHASE_A_ERROR_KEY], "pre-existing phase_a error")
        self.assertEqual(phase_b_runner.await_count, 0)
        await quartman.app.shutdown()

    async def test_startup_keeps_phase_a_healthy_for_non_blocking_degradations(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        phase_b_runner = unittest.mock.AsyncMock(return_value=None)

        async def _degraded_bootstrap(_app: Quart) -> None:
            state = quartman._bootstrap_state()
            state[quartman.PHASE_A_CAPABILITY_STATUSES_KEY] = {
                "provider_readiness.optional.email_gateway": quartman.PHASE_STATUS_DEGRADED
            }
            state[quartman.PHASE_A_ERROR_KEY] = None
            state[quartman.PHASE_A_BLOCKING_FAILURES_KEY] = []
            state[quartman.PHASE_A_NON_BLOCKING_DEGRADATIONS_KEY] = [
                "provider_readiness.optional.email_gateway"
            ]

        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=[],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            )
        )

        with (
            unittest.mock.patch.object(quartman.di, "container", container),
            unittest.mock.patch.object(quartman, "bootstrap_app", new=_degraded_bootstrap),
            unittest.mock.patch.object(quartman, "run_platform_clients", new=phase_b_runner),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(),
            ),
        ):
            await quartman.app.startup()
            state = quartman._bootstrap_state()
            self.assertEqual(state[quartman.PHASE_A_STATUS_KEY], quartman.PHASE_STATUS_HEALTHY)
            self.assertEqual(state[quartman.PHASE_A_ERROR_KEY], None)
            await quartman.app.shutdown()

    async def test_startup_preserves_existing_phase_a_error_for_degraded_capabilities(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        phase_b_runner = unittest.mock.AsyncMock(return_value=None)

        async def _degraded_bootstrap(_app: Quart) -> None:
            state = quartman._bootstrap_state()
            state[quartman.PHASE_A_CAPABILITY_STATUSES_KEY] = {
                "container_readiness": quartman.PHASE_STATUS_DEGRADED
            }
            state[quartman.PHASE_A_ERROR_KEY] = "container probe failed"

        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=[],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            )
        )

        with (
            unittest.mock.patch.object(quartman.di, "container", container),
            unittest.mock.patch.object(quartman, "bootstrap_app", new=_degraded_bootstrap),
            unittest.mock.patch.object(quartman, "run_platform_clients", new=phase_b_runner),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(),
            ),
        ):
            await quartman.app.startup()
            state = quartman._bootstrap_state()
            self.assertEqual(state[quartman.PHASE_A_STATUS_KEY], quartman.PHASE_STATUS_HEALTHY)
            self.assertEqual(state[quartman.PHASE_A_ERROR_KEY], "container probe failed")
            await quartman.app.shutdown()

    async def test_startup_fails_fast_on_invalid_platform_config_before_phase_b_task(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=["web", "unknown"],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            )
        )

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                container,
            ),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=unittest.mock.AsyncMock(),
            ) as phase_b_runner,
            self.assertRaises(BootstrapConfigError),
        ):
            await quartman.app.startup()

        state = quartman._bootstrap_state()
        self.assertEqual(phase_b_runner.await_count, 0)
        self.assertIsNone(state.get(quartman._PLATFORM_CLIENTS_TASK_KEY))

    async def test_startup_fails_fast_on_unsupported_telnet_platform_before_phase_b_task(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=["telnet"],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            ),
        )

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                container,
            ),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=unittest.mock.AsyncMock(),
            ) as phase_b_runner,
            self.assertRaises(BootstrapConfigError),
        ):
            await quartman.app.startup()

        state = quartman._bootstrap_state()
        self.assertEqual(phase_b_runner.await_count, 0)
        self.assertIsNone(state.get(quartman._PLATFORM_CLIENTS_TASK_KEY))

    async def test_startup_fails_fast_on_relational_web_miswire_before_phase_b_task(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=["web"],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
                modules=unittest.mock.Mock(
                    core=unittest.mock.Mock(
                        gateway=unittest.mock.Mock(
                            storage=unittest.mock.Mock(relational="configured")
                        )
                    )
                ),
            )
        )
        container.relational_storage_gateway = object()

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                container,
            ),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=unittest.mock.AsyncMock(),
            ) as phase_b_runner,
            self.assertRaises(BootstrapConfigError),
        ):
            await quartman.app.startup()

        state = quartman._bootstrap_state()
        self.assertEqual(phase_b_runner.await_count, 0)
        self.assertIsNone(state.get(quartman._PLATFORM_CLIENTS_TASK_KEY))

    async def test_shutdown_cancels_whatsapp_phase_b_task(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        import mugen as mugen_mod  # pylint: disable=import-outside-toplevel

        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=["whatsapp"],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            )
        )
        config = unittest.mock.Mock()
        config.mugen = unittest.mock.Mock(
            platforms=["whatsapp"],
            runtime=_runtime_mock(startup_timeout_seconds=30.0),
        )
        whatsapp_started = asyncio.Event()

        async def _blocking_whatsapp(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = degraded_callback
            if callable(started_callback):
                started_callback()
            if callable(healthy_callback):
                healthy_callback()
            whatsapp_started.set()
            await asyncio.Event().wait()

        async def _phase_b_runner(_app: Quart) -> None:
            await mugen_mod.run_platform_clients(
                _app,
                config_provider=lambda: config,
                logger_provider=lambda: _app.logger,
                whatsapp_provider=lambda: None,
            )

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                container,
            ),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=_phase_b_runner,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "run_whatsapp_client",
                new=_blocking_whatsapp,
            ),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(),
            ),
        ):
            await quartman.app.startup()
            await asyncio.wait_for(whatsapp_started.wait(), timeout=1.0)

            state = quartman._bootstrap_state()
            task = state.get(quartman._PLATFORM_CLIENTS_TASK_KEY)
            self.assertIsInstance(task, asyncio.Task)
            self.assertFalse(task.done())

            await quartman.app.shutdown()

            self.assertTrue(task.done())
            self.assertIsNone(state.get(quartman._PLATFORM_CLIENTS_TASK_KEY))

    async def test_done_callback_logs_cancelled_task(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        block = asyncio.Event()
        task = asyncio.create_task(block.wait())
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        with self.assertLogs(logger=app.name, level="INFO") as logs:
            quartman._on_platform_clients_done(task, started_at=0.0)

        self.assertTrue(any("phase_b cancelled" in msg for msg in logs.output))

    async def test_done_callback_logs_task_failure(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        async def _boom():
            raise RuntimeError("boom")

        task = asyncio.create_task(_boom())
        await asyncio.gather(task, return_exceptions=True)

        with self.assertLogs(logger=app.name, level="ERROR") as logs:
            quartman._on_platform_clients_done(task, started_at=0.0)

        self.assertTrue(any("phase_b failed" in msg for msg in logs.output))

    async def test_done_callback_keeps_healthy_when_stopped_critical_exit_is_allowed(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        state = quartman._bootstrap_state()
        state[quartman.PHASE_B_STATUS_KEY] = quartman.PHASE_STATUS_HEALTHY
        state[quartman._PHASE_B_CRITICAL_PLATFORMS_KEY] = ["web"]
        state[quartman._PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = False
        state[quartman.PHASE_B_PLATFORM_STATUSES_KEY] = {"web": quartman.PHASE_STATUS_STOPPED}
        state[quartman.PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}

        task = asyncio.create_task(asyncio.sleep(0))
        await task

        quartman._on_platform_clients_done(task, started_at=0.0)
        self.assertEqual(
            state[quartman.PHASE_B_STATUS_KEY],
            quartman.PHASE_STATUS_HEALTHY,
        )

    async def test_done_callback_parses_degrade_flag_values(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        state = quartman._bootstrap_state()

        async def _completed_task() -> asyncio.Task:
            task = asyncio.create_task(asyncio.sleep(0))
            await task
            return task

        state.clear()
        state[quartman.PHASE_B_STATUS_KEY] = quartman.PHASE_STATUS_HEALTHY
        state[quartman._PHASE_B_CRITICAL_PLATFORMS_KEY] = ["web"]
        state[quartman._PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = "on"
        state[quartman.PHASE_B_PLATFORM_STATUSES_KEY] = {"web": quartman.PHASE_STATUS_STOPPED}
        state[quartman.PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}
        quartman._on_platform_clients_done(await _completed_task(), started_at=0.0)
        self.assertEqual(state[quartman.PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_DEGRADED)

        state.clear()
        state[quartman.PHASE_B_STATUS_KEY] = quartman.PHASE_STATUS_HEALTHY
        state[quartman._PHASE_B_CRITICAL_PLATFORMS_KEY] = ["web"]
        state[quartman._PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = "off"
        state[quartman.PHASE_B_PLATFORM_STATUSES_KEY] = {"web": quartman.PHASE_STATUS_STOPPED}
        state[quartman.PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}
        quartman._on_platform_clients_done(await _completed_task(), started_at=0.0)
        self.assertEqual(state[quartman.PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_HEALTHY)

        state.clear()
        state[quartman.PHASE_B_STATUS_KEY] = quartman.PHASE_STATUS_HEALTHY
        state[quartman._PHASE_B_CRITICAL_PLATFORMS_KEY] = ["web"]
        state[quartman._PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = "invalid"
        state[quartman.PHASE_B_PLATFORM_STATUSES_KEY] = {"web": quartman.PHASE_STATUS_HEALTHY}
        state[quartman.PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}
        quartman._on_platform_clients_done(await _completed_task(), started_at=0.0)
        self.assertEqual(state[quartman.PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_HEALTHY)

        state.clear()
        state[quartman.PHASE_B_STATUS_KEY] = quartman.PHASE_STATUS_HEALTHY
        state[quartman._PHASE_B_CRITICAL_PLATFORMS_KEY] = ["web"]
        state[quartman._PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = object()
        state[quartman.PHASE_B_PLATFORM_STATUSES_KEY] = {"web": quartman.PHASE_STATUS_HEALTHY}
        state[quartman.PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}
        quartman._on_platform_clients_done(await _completed_task(), started_at=0.0)
        self.assertEqual(state[quartman.PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_HEALTHY)

    async def test_startup_skips_when_platform_task_already_active(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        active_task = asyncio.create_task(asyncio.Event().wait())
        quartman._bootstrap_state()[quartman._PLATFORM_CLIENTS_TASK_KEY] = active_task

        with (
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=unittest.mock.AsyncMock(),
            ) as phase_b_runner,
            self.assertLogs(logger=app.name, level="WARNING") as logs,
        ):
            await quartman.app.startup()

        self.assertEqual(phase_b_runner.await_count, 0)
        self.assertTrue(any("already active" in msg for msg in logs.output))
        with (
            unittest.mock.patch.object(
                quartman,
                "_resolve_shutdown_timeout_seconds",
                return_value=0.01,
            ),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(),
            ),
        ):
            await quartman.app.shutdown()

    async def test_startup_fails_when_container_config_is_missing(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                object(),
            ),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=unittest.mock.AsyncMock(),
            ) as phase_b_runner,
            self.assertRaises(BootstrapConfigError),
        ):
            await quartman.app.startup()

        self.assertEqual(phase_b_runner.await_count, 0)

    async def test_startup_rejects_missing_runtime_config(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = object()

        phase_b_runner = unittest.mock.AsyncMock()

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                container,
            ),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=phase_b_runner,
            ),
            self.assertRaises(BootstrapConfigError),
        ):
            await quartman.app.startup()

        state = quartman._bootstrap_state()
        self.assertEqual(phase_b_runner.await_count, 0)
        self.assertIsNone(state.get(quartman._PLATFORM_CLIENTS_TASK_KEY))

    async def test_phase_b_startup_timeout_resolution_reads_container_config(self) -> None:
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                runtime=_runtime_mock(startup_timeout_seconds=12.5)
            )
        )
        self.assertEqual(
            resolve_phase_b_startup_timeout_seconds(container.config),
            12.5,
        )

    async def test_resolve_shutdown_timeout_seconds_requires_runtime_config(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        with unittest.mock.patch.object(quartman.di, "container", object()):
            with self.assertRaisesRegex(BootstrapConfigError, "Configuration unavailable"):
                quartman._resolve_shutdown_timeout_seconds()

    async def test_resolve_shutdown_timeout_seconds_wraps_container_attribute_errors(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        class _RaisingContainer:  # pylint: disable=too-few-public-methods
            @property
            def config(self):
                raise RuntimeError("container unavailable")

        with unittest.mock.patch.object(quartman.di, "container", _RaisingContainer()):
            with self.assertRaisesRegex(BootstrapConfigError, "Configuration unavailable"):
                quartman._resolve_shutdown_timeout_seconds()

    async def test_startup_wraps_container_attribute_errors_during_phase_b_resolution(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        class _RaisingContainer:  # pylint: disable=too-few-public-methods
            @property
            def config(self):
                raise RuntimeError("container unavailable")

        with (
            unittest.mock.patch.object(quartman.di, "container", _RaisingContainer()),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=unittest.mock.AsyncMock(),
            ),
            self.assertRaisesRegex(BootstrapConfigError, "Configuration unavailable"),
        ):
            await quartman.app.startup()

    async def test_startup_rejects_phase_b_plan_missing_timeout_value(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=[],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            )
        )

        with (
            unittest.mock.patch.object(quartman.di, "container", container),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "start_phase_b_runtime",
                new=unittest.mock.AsyncMock(
                    side_effect=RuntimeError(
                        "Invalid runtime configuration: startup timeout is required."
                    )
                ),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=unittest.mock.AsyncMock(),
            ) as phase_b_runner,
            self.assertRaises(BootstrapConfigError),
        ):
            await quartman.app.startup()

        self.assertEqual(phase_b_runner.await_count, 0)

    async def test_startup_timeout_failure_cancels_phase_b_task(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=[],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            )
        )

        async def _blocking_runner(_app: Quart) -> None:
            await asyncio.Event().wait()

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                container,
            ),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "wait_for_critical_startup",
                new=unittest.mock.AsyncMock(
                    side_effect=RuntimeError("critical startup timeout")
                ),
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=_blocking_runner,
            ),
            self.assertRaises(BootstrapConfigError),
        ):
            await quartman.app.startup()

        state = quartman._bootstrap_state()
        self.assertEqual(state[PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_DEGRADED)
        self.assertIn(
            state[PHASE_B_ERROR_KEY],
            {"critical startup timeout", "phase_b task cancelled unexpectedly"},
        )
        self.assertIsNone(state.get(quartman._PLATFORM_CLIENTS_TASK_KEY))

    async def test_startup_timeout_failure_when_phase_b_task_already_completed(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                platforms=[],
                runtime=_runtime_mock(startup_timeout_seconds=30.0),
            )
        )

        async def _done_runner(_app: Quart) -> None:
            return None

        async def _late_failure(*args, **kwargs):
            _ = (args, kwargs)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            raise RuntimeError("critical startup timeout")

        with (
            unittest.mock.patch.object(
                quartman.di,
                "container",
                container,
            ),
            unittest.mock.patch.object(
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "wait_for_critical_startup",
                new=_late_failure,
            ),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=_done_runner,
            ),
            self.assertRaises(BootstrapConfigError),
        ):
            await quartman.app.startup()

        state = quartman._bootstrap_state()
        self.assertEqual(state[PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_DEGRADED)
        self.assertEqual(state[PHASE_B_ERROR_KEY], "critical startup timeout")
        self.assertIsNone(state.get(quartman._PLATFORM_CLIENTS_TASK_KEY))

    async def test_shutdown_handles_cancelled_error_from_task_await(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        task = asyncio.create_task(asyncio.Event().wait())
        quartman._bootstrap_state()[quartman._PLATFORM_CLIENTS_TASK_KEY] = task

        with (
            unittest.mock.patch.object(
                quartman,
                "_resolve_shutdown_timeout_seconds",
                return_value=0.01,
            ),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(),
            ),
            self.assertLogs(logger=app.name, level="DEBUG") as logs,
        ):
            await quartman.shutdown()

        self.assertTrue(task.done())
        self.assertTrue(
            any("cancelled during shutdown" in msg for msg in logs.output)
        )
        self.assertIsNone(
            quartman._bootstrap_state().get(quartman._PLATFORM_CLIENTS_TASK_KEY)
        )

    async def test_shutdown_marks_degraded_when_task_timeout_expires(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        task = asyncio.create_task(asyncio.Event().wait())
        quartman._bootstrap_state()[quartman._PLATFORM_CLIENTS_TASK_KEY] = task

        async def _timeout_cancel(
            bootstrap_state,
            *,
            timeout_seconds,
            logger,
        ):  # noqa: ARG001
            bootstrap_state[quartman.PHASE_B_STATUS_KEY] = quartman.PHASE_STATUS_DEGRADED
            bootstrap_state[quartman.PHASE_B_ERROR_KEY] = (
                "phase_b platform shutdown timed out after "
                f"{timeout_seconds:.2f}s (web)"
            )
            platform_statuses = bootstrap_state.get(quartman.PHASE_B_PLATFORM_STATUSES_KEY, {})
            if not isinstance(platform_statuses, dict):
                platform_statuses = {}
            platform_statuses["web"] = quartman.PHASE_STATUS_DEGRADED
            bootstrap_state[quartman.PHASE_B_PLATFORM_STATUSES_KEY] = platform_statuses
            platform_errors = bootstrap_state.get(quartman.PHASE_B_PLATFORM_ERRORS_KEY, {})
            if not isinstance(platform_errors, dict):
                platform_errors = {}
            platform_errors["web"] = f"shutdown timed out after {timeout_seconds:.2f}s"
            bootstrap_state[quartman.PHASE_B_PLATFORM_ERRORS_KEY] = platform_errors
            bootstrap_state[quartman.PHASE_B_PLATFORM_TASKS_KEY] = {"web": task}
            raise PhaseBShutdownError(bootstrap_state[quartman.PHASE_B_ERROR_KEY])

        with (
            unittest.mock.patch.object(
                quartman,
                "_resolve_shutdown_timeout_seconds",
                return_value=0.01,
            ),
            unittest.mock.patch.object(
                quartman,
                "cancel_registered_platform_tasks",
                new=unittest.mock.AsyncMock(
                    side_effect=_timeout_cancel
                ),
            ),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(),
            ),
            self.assertLogs(logger=app.name, level="ERROR") as logs,
            self.assertRaises(PhaseBShutdownError),
        ):
            await quartman.shutdown()

        state = quartman._bootstrap_state()
        self.assertEqual(state[quartman.PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_DEGRADED)
        self.assertIn("phase_b platform shutdown timed out after", str(state[quartman.PHASE_B_ERROR_KEY]))
        self.assertTrue(any("shutdown failed" in msg for msg in logs.output))
        self.assertIn("web", state[PHASE_B_PLATFORM_TASKS_KEY])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_shutdown_handles_non_cancelled_error_from_task_await(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        async def _raise_after_cancel() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError as exc:
                raise RuntimeError("shutdown failure") from exc

        task = asyncio.create_task(_raise_after_cancel())
        await asyncio.sleep(0)
        quartman._bootstrap_state()[quartman._PLATFORM_CLIENTS_TASK_KEY] = task
        shutdown_container = unittest.mock.AsyncMock()

        with (
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=shutdown_container,
            ),
            unittest.mock.patch.object(
                quartman,
                "_resolve_shutdown_timeout_seconds",
                return_value=0.01,
            ),
            self.assertLogs(logger=app.name, level="ERROR") as logs,
            self.assertRaises(PhaseBShutdownError),
        ):
            await quartman.shutdown()

        self.assertTrue(any("shutdown failed" in msg for msg in logs.output))
        shutdown_container.assert_awaited_once_with()
        self.assertEqual(
            quartman._bootstrap_state()[quartman.PHASE_B_STATUS_KEY],
            quartman.PHASE_STATUS_DEGRADED,
        )
        self.assertIsNone(
            quartman._bootstrap_state().get(quartman._PLATFORM_CLIENTS_TASK_KEY)
        )

    async def test_shutdown_normalizes_platform_task_registry_after_container_shutdown(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        async def _mutating_shutdown_container() -> None:
            quartman._bootstrap_state()[quartman.PHASE_B_PLATFORM_TASKS_KEY] = "invalid"

        with (
            unittest.mock.patch.object(
                quartman,
                "_resolve_shutdown_timeout_seconds",
                return_value=0.01,
            ),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=_mutating_shutdown_container,
            ),
        ):
            await quartman.shutdown()

        self.assertEqual(
            quartman._bootstrap_state()[quartman.PHASE_B_PLATFORM_TASKS_KEY],
            {},
        )

    async def test_runtime_controls_default_when_container_config_missing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "mugen.runtime.profile"):
            resolve_phase_b_runtime_controls(object())

    async def test_runtime_controls_reject_invalid_grace_values(self) -> None:
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                runtime=unittest.mock.Mock(
                    profile="platform_full",
                    provider_readiness_timeout_seconds=15.0,
                    provider_shutdown_timeout_seconds=10.0,
                    shutdown_timeout_seconds=60.0,
                    phase_b=unittest.mock.Mock(
                        startup_timeout_seconds=30.0,
                        readiness_grace_seconds="invalid",
                        critical_platforms=[" WEB ", "", "whatsapp"],
                        degrade_on_critical_exit="off",
                    )
                ),
                platforms=["matrix"],
            )
        )
        with self.assertRaisesRegex(RuntimeError, "readiness_grace_seconds"):
            resolve_phase_b_runtime_controls(container.config)

        container.config.mugen.runtime.phase_b.readiness_grace_seconds = 0
        grace, critical, degrade_on_critical_exit = resolve_phase_b_runtime_controls(
            container.config
        )
        self.assertEqual(grace, 0.0)
        self.assertEqual(critical, ["web", "whatsapp"])
        self.assertFalse(degrade_on_critical_exit)

        container.config.mugen.runtime.phase_b.readiness_grace_seconds = -10
        container.config.mugen.runtime.phase_b.critical_platforms = None
        container.config.mugen.runtime.phase_b.degrade_on_critical_exit = "invalid"
        with self.assertRaisesRegex(RuntimeError, "readiness_grace_seconds"):
            resolve_phase_b_runtime_controls(container.config)

    async def test_shutdown_container_propagates_exception(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        with (
            unittest.mock.patch.object(
                quartman.di,
                "shutdown_container_async",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            await quartman._shutdown_container()

    async def test_shutdown_aggregates_phase_b_and_container_failures(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        task = asyncio.create_task(asyncio.Event().wait())
        quartman._bootstrap_state()[quartman._PLATFORM_CLIENTS_TASK_KEY] = task

        with (
            unittest.mock.patch.object(
                quartman,
                "_resolve_shutdown_timeout_seconds",
                return_value=0.01,
            ),
            unittest.mock.patch.object(
                quartman,
                "cancel_registered_platform_tasks",
                new=unittest.mock.AsyncMock(
                    side_effect=PhaseBShutdownError("phase_b failed")
                ),
            ),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(
                    side_effect=RuntimeError("container failed")
                ),
            ),
            self.assertRaisesRegex(
                PhaseBShutdownError,
                "phase_b failed; container shutdown failed: RuntimeError: container failed",
            ),
        ):
            await quartman.shutdown()

        state = quartman._bootstrap_state()
        self.assertEqual(state[quartman.PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_DEGRADED)
        self.assertIn("phase_b failed", state[quartman.PHASE_B_ERROR_KEY])
        self.assertIn("container shutdown failed", state[quartman.PHASE_B_ERROR_KEY])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_shutdown_marks_degraded_when_container_shutdown_fails(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        with (
            unittest.mock.patch.object(
                quartman,
                "_resolve_shutdown_timeout_seconds",
                return_value=0.01,
            ),
            unittest.mock.patch.object(
                quartman,
                "_shutdown_container",
                new=unittest.mock.AsyncMock(
                    side_effect=RuntimeError("container failed")
                ),
            ),
            self.assertRaisesRegex(
                PhaseBShutdownError,
                "container shutdown failed: RuntimeError: container failed",
            ),
        ):
            await quartman.shutdown()

        state = quartman._bootstrap_state()
        self.assertEqual(state[quartman.PHASE_B_STATUS_KEY], quartman.PHASE_STATUS_DEGRADED)
        self.assertIn("container shutdown failed", state[quartman.PHASE_B_ERROR_KEY])

    async def test_runtime_controls_return_empty_critical_list_for_non_list_platforms(
        self,
    ) -> None:
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                runtime=unittest.mock.Mock(
                    profile="platform_full",
                    provider_readiness_timeout_seconds=15.0,
                    provider_shutdown_timeout_seconds=10.0,
                    shutdown_timeout_seconds=60.0,
                    phase_b=unittest.mock.Mock(
                        startup_timeout_seconds=30.0,
                        readiness_grace_seconds=3,
                        critical_platforms=None,
                        degrade_on_critical_exit=True,
                    )
                ),
                platforms="web",
            )
        )
        grace, critical, degrade_on_critical_exit = resolve_phase_b_runtime_controls(
            container.config
        )

        self.assertEqual(grace, 3.0)
        self.assertEqual(critical, [])
        self.assertTrue(degrade_on_critical_exit)

    async def test_runtime_controls_parse_true_and_fallback_values(self) -> None:
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                runtime=unittest.mock.Mock(
                    profile="platform_full",
                    provider_readiness_timeout_seconds=15.0,
                    provider_shutdown_timeout_seconds=10.0,
                    shutdown_timeout_seconds=60.0,
                    phase_b=unittest.mock.Mock(
                        startup_timeout_seconds=30.0,
                        readiness_grace_seconds=1,
                        critical_platforms=["web"],
                        degrade_on_critical_exit="on",
                    )
                ),
                platforms=["web"],
            )
        )
        _, _, degrade_on_critical_exit = resolve_phase_b_runtime_controls(
            container.config
        )
        self.assertTrue(degrade_on_critical_exit)

        container.config.mugen.runtime.phase_b.degrade_on_critical_exit = object()
        _, _, degrade_on_critical_exit = resolve_phase_b_runtime_controls(
            container.config
        )
        self.assertTrue(degrade_on_critical_exit)

    async def test_done_callback_marks_stopped_on_clean_shutdown_completion(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        state = quartman._bootstrap_state()
        state[SHUTDOWN_REQUESTED_KEY] = True

        task = asyncio.create_task(asyncio.sleep(0))
        await task
        quartman._on_platform_clients_done(task, started_at=0.0)

        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STOPPED)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

    async def test_done_callback_handles_non_dict_platform_state_maps(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        state = quartman._bootstrap_state()
        state[SHUTDOWN_REQUESTED_KEY] = False
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_PLATFORM_STATUSES_KEY] = "invalid"
        state[PHASE_B_PLATFORM_ERRORS_KEY] = "invalid"
        state[quartman._PHASE_B_CRITICAL_PLATFORMS_KEY] = "invalid"

        task = asyncio.create_task(asyncio.sleep(0))
        await task
        quartman._on_platform_clients_done(task, started_at=0.0)

        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)
