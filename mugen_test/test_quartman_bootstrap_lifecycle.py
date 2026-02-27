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
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STOPPED,
    SHUTDOWN_REQUESTED_KEY,
    BootstrapConfigError,
    ExtensionLoadError,
)


def _import_quartman_with_app(app: Quart):
    sys.modules.pop("quartman", None)
    with unittest.mock.patch("mugen.create_quart_app", return_value=app):
        return import_module("quartman")


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

        with (
            unittest.mock.patch.object(quartman, "bootstrap_app", new=_blocking_bootstrap),
            unittest.mock.patch.object(
                quartman,
                "run_platform_clients",
                new=phase_b_runner,
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

    async def test_shutdown_cancels_whatsapp_phase_b_task(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        import mugen as mugen_mod  # pylint: disable=import-outside-toplevel

        config = unittest.mock.Mock()
        config.mugen = unittest.mock.Mock(platforms=["whatsapp"])
        whatsapp_started = asyncio.Event()

        async def _blocking_whatsapp() -> None:
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
                quartman,
                "bootstrap_app",
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            unittest.mock.patch.object(
                quartman,
                "_resolve_phase_b_runtime_controls",
                return_value=(0.0, ["whatsapp"], True),
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
        await quartman.app.shutdown()

    async def test_shutdown_handles_cancelled_error_from_task_await(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        task = asyncio.create_task(asyncio.Event().wait())
        quartman._bootstrap_state()[quartman._PLATFORM_CLIENTS_TASK_KEY] = task

        with self.assertLogs(logger=app.name, level="DEBUG") as logs:
            await quartman.shutdown()

        self.assertTrue(task.done())
        self.assertTrue(
            any("cancelled during shutdown" in msg for msg in logs.output)
        )
        self.assertIsNone(
            quartman._bootstrap_state().get(quartman._PLATFORM_CLIENTS_TASK_KEY)
        )

    async def test_runtime_controls_default_when_container_config_missing(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        with unittest.mock.patch.object(quartman.di, "container", object()):
            grace, critical, degrade_on_critical_exit = (
                quartman._resolve_phase_b_runtime_controls()
            )

        self.assertEqual(grace, 0.0)
        self.assertEqual(critical, [])
        self.assertTrue(degrade_on_critical_exit)

    async def test_runtime_controls_normalize_invalid_values(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                runtime=unittest.mock.Mock(
                    phase_b=unittest.mock.Mock(
                        readiness_grace_seconds="invalid",
                        critical_platforms=[" WEB ", "", "whatsapp"],
                        degrade_on_critical_exit="off",
                    )
                ),
                platforms=["matrix"],
            )
        )

        with unittest.mock.patch.object(quartman.di, "container", container):
            grace, critical, degrade_on_critical_exit = (
                quartman._resolve_phase_b_runtime_controls()
            )

        self.assertEqual(grace, 0.0)
        self.assertEqual(critical, ["web", "whatsapp"])
        self.assertFalse(degrade_on_critical_exit)

        container.config.mugen.runtime.phase_b.readiness_grace_seconds = -10
        container.config.mugen.runtime.phase_b.critical_platforms = None
        container.config.mugen.runtime.phase_b.degrade_on_critical_exit = "invalid"
        with unittest.mock.patch.object(quartman.di, "container", container):
            grace, critical, degrade_on_critical_exit = (
                quartman._resolve_phase_b_runtime_controls()
            )

        self.assertEqual(grace, 0.0)
        self.assertEqual(critical, ["matrix"])
        self.assertTrue(degrade_on_critical_exit)

    async def test_shutdown_container_logs_warning_on_exception(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)

        with (
            unittest.mock.patch.object(
                quartman.di,
                "shutdown_container",
                side_effect=RuntimeError("boom"),
            ),
            self.assertLogs(logger=app.name, level="WARNING") as logs,
        ):
            quartman._shutdown_container()

        self.assertTrue(any("Container shutdown failed" in msg for msg in logs.output))

    async def test_runtime_controls_return_empty_critical_list_for_non_list_platforms(
        self,
    ) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                runtime=unittest.mock.Mock(
                    phase_b=unittest.mock.Mock(
                        readiness_grace_seconds=3,
                        critical_platforms=None,
                        degrade_on_critical_exit=True,
                    )
                ),
                platforms="web",
            )
        )

        with unittest.mock.patch.object(quartman.di, "container", container):
            grace, critical, degrade_on_critical_exit = (
                quartman._resolve_phase_b_runtime_controls()
            )

        self.assertEqual(grace, 3.0)
        self.assertEqual(critical, [])
        self.assertTrue(degrade_on_critical_exit)

    async def test_runtime_controls_parse_true_and_fallback_values(self) -> None:
        app = Quart("quartman_test")
        quartman = _import_quartman_with_app(app)
        container = unittest.mock.Mock()
        container.config = unittest.mock.Mock(
            mugen=unittest.mock.Mock(
                runtime=unittest.mock.Mock(
                    phase_b=unittest.mock.Mock(
                        readiness_grace_seconds=1,
                        critical_platforms=["web"],
                        degrade_on_critical_exit="on",
                    )
                ),
                platforms=["web"],
            )
        )

        with unittest.mock.patch.object(quartman.di, "container", container):
            _, _, degrade_on_critical_exit = quartman._resolve_phase_b_runtime_controls()
        self.assertTrue(degrade_on_critical_exit)

        container.config.mugen.runtime.phase_b.degrade_on_critical_exit = object()
        with unittest.mock.patch.object(quartman.di, "container", container):
            _, _, degrade_on_critical_exit = quartman._resolve_phase_b_runtime_controls()
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
