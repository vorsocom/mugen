"""Provides unit tests for mugen.run_platform_clients."""

import asyncio
from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart

import mugen as mugen_mod
from mugen import (
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_PLATFORM_TASKS_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STOPPED,
    PHASE_STATUS_STARTING,
    SHUTDOWN_REQUESTED_KEY,
    BootstrapConfigError,
    bootstrap_app,
    run_platform_clients,
    run_whatsapp_client,
)


def _test_config(*, platforms: list[str], mh_mode: str = "optional") -> SimpleNamespace:
    mugen_cfg = SimpleNamespace(
        platforms=list(platforms),
        messaging=SimpleNamespace(mh_mode=mh_mode),
        runtime=SimpleNamespace(
            profile="platform_full",
            provider_readiness_timeout_seconds=15.0,
            provider_shutdown_timeout_seconds=10.0,
            shutdown_timeout_seconds=60.0,
            phase_b=SimpleNamespace(
                startup_timeout_seconds=30.0,
                readiness_grace_seconds=0.0,
                critical_platforms=list(platforms),
                degrade_on_critical_exit=True,
            )
        ),
    )
    if (
        "web" in platforms
        or "line" in platforms
        or "signal" in platforms
        or "telegram" in platforms
        or "wechat" in platforms
    ):
        client_cfg = {}
        if "web" in platforms:
            client_cfg["web"] = "default"
        if "line" in platforms:
            client_cfg["line"] = "default"
        if "signal" in platforms:
            client_cfg["signal"] = "default"
        if "telegram" in platforms:
            client_cfg["telegram"] = "default"
        if "wechat" in platforms:
            client_cfg["wechat"] = "default"
        mugen_cfg.modules = SimpleNamespace(
            core=SimpleNamespace(
                client=SimpleNamespace(**client_cfg),
                gateway=SimpleNamespace(
                    storage=SimpleNamespace(
                        relational="configured",
                        web_runtime="configured",
                    ),
                )
            )
        )
    return SimpleNamespace(mugen=mugen_cfg)


class _ReadyProvider:  # pylint: disable=too-few-public-methods
    def check_readiness(self) -> None:
        return None


class TestMuGenInitRunPlatformClients(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_platform_clients."""

    def setUp(self) -> None:
        self._container_patch = unittest.mock.patch.object(
            mugen_mod.di,
            "container",
            SimpleNamespace(
                messaging_service=None,
                line_client=None,
                signal_client=None,
                telegram_client=None,
                wechat_client=None,
                whatsapp_client=None,
                web_client=object(),
                relational_storage_gateway=_ReadyProvider(),
                web_runtime_store=_ReadyProvider(),
                get_readiness_report=lambda: None,
            ),
        )
        self._container_patch.start()
        self.addCleanup(self._container_patch.stop)

    async def test_platforms_configuration_unavailable(self) -> None:
        """Test effects of missing platforms configuration."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(
                    profile="platform_full",
                    provider_readiness_timeout_seconds=15.0,
                    provider_shutdown_timeout_seconds=10.0,
                    shutdown_timeout_seconds=60.0,
                    phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
                )
            )
        )

        with (
            self.assertLogs(logger="test_app", level="ERROR"),
            self.assertRaises(BootstrapConfigError),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_run_platform_clients_wraps_config_provider_failure(self) -> None:
        app = Quart("test_app")

        with self.assertRaisesRegex(BootstrapConfigError, "Configuration unavailable"):
            await run_platform_clients(
                app,
                config_provider=lambda: (_ for _ in ()).throw(RuntimeError("bad config")),
                logger_provider=lambda: app.logger,
            )

    async def test_run_platform_clients_wraps_logger_provider_failure(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=[])

        with self.assertRaisesRegex(BootstrapConfigError, "Logging provider unavailable"):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: (_ for _ in ()).throw(RuntimeError("bad logger")),
            )

    async def test_matrix_platform_enabled(self) -> None:
        """Test running matrix platform."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = _test_config(platforms=["matrix"])

        _run_matrix_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_matrix_client", new=_run_matrix_client
            ),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running matrix client.",
            )

    async def test_telnet_platform_rejected_by_core_runtime(self) -> None:
        """Core runtime no longer accepts telnet platform."""
        app = Quart("test_app")
        config = _test_config(platforms=["telnet"])

        with self.assertRaises(BootstrapConfigError):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_whatsapp_platform_enabled(self) -> None:
        """Test running whatsapp platform."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = _test_config(platforms=["whatsapp"])

        _run_whatsapp_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_whatsapp_client", new=_run_whatsapp_client
            ),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running whatsapp client.",
            )

    async def test_telegram_platform_enabled(self) -> None:
        """Test running telegram platform."""
        app = Quart("test_app")
        config = _test_config(platforms=["telegram"])

        _run_telegram_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_telegram_client", new=_run_telegram_client
            ),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running telegram client.",
            )

    async def test_line_platform_enabled(self) -> None:
        """Test running line platform."""
        app = Quart("test_app")
        config = _test_config(platforms=["line"])

        _run_line_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_line_client", new=_run_line_client
            ),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running line client.",
            )

    async def test_signal_platform_enabled(self) -> None:
        """Test running signal platform."""
        app = Quart("test_app")
        config = _test_config(platforms=["signal"])

        _run_signal_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_signal_client", new=_run_signal_client
            ),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running signal client.",
            )

    async def test_wechat_platform_enabled(self) -> None:
        """Test running wechat platform."""
        app = Quart("test_app")
        config = _test_config(platforms=["wechat"])

        _run_wechat_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_wechat_client", new=_run_wechat_client
            ),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running wechat client.",
            )

    async def test_web_platform_enabled(self) -> None:
        """Test running web platform."""
        app = Quart("test_app")
        config = _test_config(platforms=["web"])

        _run_web_client = unittest.mock.AsyncMock()

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_web_client",
                new=_run_web_client,
            ),
        ):
            await run_platform_clients(
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
        config = _test_config(platforms=["whatsapp"])

        _run_whatsapp_client = unittest.mock.AsyncMock(
            side_effect=asyncio.exceptions.CancelledError
        )

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch(
                target="mugen.run_whatsapp_client", new=_run_whatsapp_client
            ),
        ):
            await run_platform_clients(
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
        config = _test_config(platforms=["whatsapp"])

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
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: whatsapp_client,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Running whatsapp client.",
            )

    async def test_run_platform_clients_marks_phase_b_degraded_on_critical_exit(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["matrix"])
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
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn("matrix", str(state[PHASE_B_ERROR_KEY]))
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["matrix"], PHASE_STATUS_DEGRADED)
        self.assertIsNotNone(state[PHASE_B_PLATFORM_ERRORS_KEY]["matrix"])

    async def test_validate_phase_b_runtime_config_raises_without_logger_for_invalid_shape(
        self,
    ) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms="web",
                runtime=SimpleNamespace(
                    profile="platform_full",
                    provider_readiness_timeout_seconds=15.0,
                    provider_shutdown_timeout_seconds=10.0,
                    shutdown_timeout_seconds=60.0,
                    phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
                ),
            )
        )
        with self.assertRaises(BootstrapConfigError):
            mugen_mod.validate_phase_b_runtime_config(
                config=config,
                bootstrap_state={},
                logger=None,
            )

    async def test_run_platform_clients_keeps_platform_starting_until_started_callback(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        allow_start = asyncio.Event()
        keep_running = asyncio.Event()

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = degraded_callback
            _ = healthy_callback
            await allow_start.wait()
            if callable(started_callback):
                started_callback()
            await keep_running.wait()

        with unittest.mock.patch("mugen.run_web_client", new=_run_web_client):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.sleep(0)
            state = app.extensions["mugen"]["bootstrap"]
            self.assertEqual(
                state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
                PHASE_STATUS_STARTING,
            )
            self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STARTING)

            allow_start.set()
            await asyncio.sleep(0)
            self.assertEqual(
                state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
                PHASE_STATUS_HEALTHY,
            )

            runner.cancel()
            with self.assertRaises(asyncio.exceptions.CancelledError):
                await runner

    async def test_run_platform_clients_marks_platform_degraded_when_shutdown_timeout_expires(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        started = asyncio.Event()

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = (degraded_callback, healthy_callback)
            if callable(started_callback):
                started_callback()
            started.set()
            await asyncio.Event().wait()

        async def _timeout_cancel(
            bootstrap_state,
            *,
            timeout_seconds,
            logger,
        ):  # noqa: ARG001
            platform_statuses = bootstrap_state.get(PHASE_B_PLATFORM_STATUSES_KEY, {})
            if not isinstance(platform_statuses, dict):
                platform_statuses = {}
            platform_statuses["web"] = PHASE_STATUS_DEGRADED
            bootstrap_state[PHASE_B_PLATFORM_STATUSES_KEY] = platform_statuses

            platform_errors = bootstrap_state.get(PHASE_B_PLATFORM_ERRORS_KEY, {})
            if not isinstance(platform_errors, dict):
                platform_errors = {}
            platform_errors["web"] = f"shutdown timed out after {timeout_seconds:.2f}s"
            bootstrap_state[PHASE_B_PLATFORM_ERRORS_KEY] = platform_errors

            bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
            bootstrap_state[PHASE_B_ERROR_KEY] = (
                "phase_b platform shutdown timed out after "
                f"{timeout_seconds:.2f}s (web)"
            )
            raise RuntimeError(bootstrap_state[PHASE_B_ERROR_KEY])

        with (
            unittest.mock.patch("mugen.run_web_client", new=_run_web_client),
            unittest.mock.patch(
                "mugen.cancel_registered_platform_tasks",
                new=unittest.mock.AsyncMock(side_effect=_timeout_cancel),
            ),
        ):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1.0)
            runner.cancel()
            with self.assertRaises(RuntimeError):
                await runner

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(
            state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertIn(
            "shutdown timed out after",
            str(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"]),
        )

    async def test_run_platform_clients_handles_partial_timeout_membership(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["matrix", "web"])
        started = asyncio.Event()

        async def _blocking_runner(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = (degraded_callback, healthy_callback)
            if callable(started_callback):
                started_callback()
            started.set()
            await asyncio.Event().wait()

        async def _partial_timeout(
            bootstrap_state,
            *,
            timeout_seconds,
            logger,
        ):  # noqa: ARG001
            platform_statuses = bootstrap_state.get(PHASE_B_PLATFORM_STATUSES_KEY, {})
            if not isinstance(platform_statuses, dict):
                platform_statuses = {}
            platform_statuses["matrix"] = PHASE_STATUS_DEGRADED
            platform_statuses["web"] = PHASE_STATUS_STOPPED
            bootstrap_state[PHASE_B_PLATFORM_STATUSES_KEY] = platform_statuses

            platform_errors = bootstrap_state.get(PHASE_B_PLATFORM_ERRORS_KEY, {})
            if not isinstance(platform_errors, dict):
                platform_errors = {}
            platform_errors["matrix"] = f"shutdown timed out after {timeout_seconds:.2f}s"
            platform_errors["web"] = None
            bootstrap_state[PHASE_B_PLATFORM_ERRORS_KEY] = platform_errors

            task_map = bootstrap_state.get(PHASE_B_PLATFORM_TASKS_KEY, {})
            if not isinstance(task_map, dict):
                task_map = {}
            bootstrap_state[PHASE_B_PLATFORM_TASKS_KEY] = {
                "matrix": task_map.get("matrix")
            }
            bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
            bootstrap_state[PHASE_B_ERROR_KEY] = (
                "phase_b platform shutdown timed out after "
                f"{timeout_seconds:.2f}s (matrix)"
            )
            raise RuntimeError(bootstrap_state[PHASE_B_ERROR_KEY])

        with (
            unittest.mock.patch("mugen.run_matrix_client", new=_blocking_runner),
            unittest.mock.patch("mugen.run_web_client", new=_blocking_runner),
            unittest.mock.patch(
                "mugen.cancel_registered_platform_tasks",
                new=unittest.mock.AsyncMock(side_effect=_partial_timeout),
            ),
        ):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1.0)
            runner.cancel()
            with self.assertRaises(RuntimeError):
                await runner

        state = app.extensions["mugen"]["bootstrap"]
        errors = state[PHASE_B_PLATFORM_ERRORS_KEY]
        timeout_errors = [value for value in errors.values() if "shutdown timed out after" in str(value)]
        self.assertEqual(len(timeout_errors), 1)

    async def test_run_platform_clients_started_callback_ignored_when_shutdown_requested(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        allow_start = asyncio.Event()

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = degraded_callback
            _ = healthy_callback
            await allow_start.wait()
            if callable(started_callback):
                started_callback()

        with unittest.mock.patch("mugen.run_web_client", new=_run_web_client):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.sleep(0)
            state = app.extensions["mugen"]["bootstrap"]
            state[SHUTDOWN_REQUESTED_KEY] = True
            allow_start.set()
            await runner

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["web"], PHASE_STATUS_STOPPED)

    async def test_run_platform_clients_ignores_started_and_degraded_callbacks_after_shutdown(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        trigger = asyncio.Event()

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            await trigger.wait()
            if callable(started_callback):
                started_callback()
            if callable(healthy_callback):
                healthy_callback()
            if callable(degraded_callback):
                degraded_callback("late error")

        with unittest.mock.patch("mugen.run_web_client", new=_run_web_client):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.sleep(0)
            state = app.extensions["mugen"]["bootstrap"]
            state[SHUTDOWN_REQUESTED_KEY] = True
            trigger.set()
            await runner

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["web"], PHASE_STATUS_STOPPED)

    async def test_run_platform_clients_marks_task_clean_exit_without_shutdown_as_degraded(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        original_parse_bool = mugen_mod._parse_bool  # pylint: disable=protected-access
        false_bool_calls = 0

        def _patched_parse_bool(value: object, *, default: bool) -> bool:
            nonlocal false_bool_calls
            if value is False:
                false_bool_calls += 1
                if false_bool_calls == 1:
                    return True
                if false_bool_calls == 2:
                    return False
            return original_parse_bool(value, default=default)

        _run_web_client = unittest.mock.AsyncMock(return_value=None)

        with (
            unittest.mock.patch("mugen._parse_bool", new=_patched_parse_bool),
            unittest.mock.patch("mugen.run_web_client", new=_run_web_client),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(
            state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertEqual(
            state[PHASE_B_PLATFORM_ERRORS_KEY]["web"],
            "platform runner stopped unexpectedly",
        )
        self.assertEqual(_run_web_client.await_count, 0)

    async def test_run_platform_clients_shutdown_guards_ignore_healthy_and_degraded_callbacks(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        original_parse_bool = mugen_mod._parse_bool  # pylint: disable=protected-access
        false_bool_calls = 0

        def _patched_parse_bool(value: object, *, default: bool) -> bool:
            nonlocal false_bool_calls
            if value is False:
                false_bool_calls += 1
                if false_bool_calls == 1:
                    return False
                if false_bool_calls in {2, 3, 4, 5}:
                    return True
            return original_parse_bool(value, default=default)

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = healthy_callback
            if callable(started_callback):
                started_callback()
            if callable(degraded_callback):
                degraded_callback("ignored after shutdown")

        with (
            unittest.mock.patch("mugen._parse_bool", new=_patched_parse_bool),
            unittest.mock.patch("mugen.run_web_client", new=_run_web_client),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(
            state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
            PHASE_STATUS_STOPPED,
        )

    async def test_run_platform_clients_ignores_duplicate_started_callback_signal(
        self,
    ) -> None:
        app = Quart("test_app")
        state = app.extensions.setdefault("mugen", {}).setdefault("bootstrap", {})
        state["phase_b_degrade_on_critical_exit"] = False
        config = _test_config(platforms=["web"])

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = degraded_callback
            _ = healthy_callback
            if callable(started_callback):
                started_callback()
                started_callback()

        with unittest.mock.patch("mugen.run_web_client", new=_run_web_client):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn(
            "exhausted restart budget",
            str(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"]),
        )

    async def test_run_platform_clients_rethrows_unexpected_type_error_from_runner(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])

        def _bad_runner(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ):  # noqa: ARG001
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            raise TypeError("boom")

        with unittest.mock.patch("mugen.run_web_client", new=_bad_runner):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn("TypeError: boom", str(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"]))

    async def test_run_platform_clients_rethrows_type_error_for_callback_aware_runner(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])

        def _bad_runner(**_kwargs):  # noqa: ANN001
            raise TypeError("boom")

        with unittest.mock.patch("mugen.run_web_client", new=_bad_runner):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn("TypeError: boom", str(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"]))

    async def test_run_platform_clients_marks_degraded_when_runner_rejects_callbacks(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])

        class _LegacyRunner:
            def __call__(self, **kwargs):  # noqa: ANN003
                if "degraded_callback" in kwargs:
                    raise TypeError("unexpected keyword argument 'degraded_callback'")
                if "started_callback" in kwargs:
                    raise TypeError("unexpected keyword argument 'started_callback'")

                async def _done() -> None:
                    return None

                return _done()

        with unittest.mock.patch("mugen.run_web_client", new=_LegacyRunner()):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertEqual(
            state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertIn(
            "TypeError: unexpected keyword argument 'degraded_callback'",
            str(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"]),
        )

    async def test_run_platform_clients_runtime_degraded_defaults_reason_when_blank(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        hold = asyncio.Event()
        degraded = asyncio.Event()

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = healthy_callback
            if callable(started_callback):
                started_callback()
            if callable(degraded_callback):
                degraded_callback(None)
                degraded.set()
            await hold.wait()

        with unittest.mock.patch("mugen.run_web_client", new=_run_web_client):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.wait_for(degraded.wait(), timeout=1.0)
            state = app.extensions["mugen"]["bootstrap"]
            self.assertEqual(
                state[PHASE_B_PLATFORM_ERRORS_KEY]["web"],
                "runtime health check failed",
            )
            runner.cancel()
            with self.assertRaises(asyncio.exceptions.CancelledError):
                await runner

    async def test_run_platform_clients_ignores_runtime_degraded_callback_after_shutdown_requested(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        trigger = asyncio.Event()

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = healthy_callback
            if callable(started_callback):
                started_callback()
            await trigger.wait()
            if callable(degraded_callback):
                degraded_callback("late runtime failure")

        with unittest.mock.patch("mugen.run_web_client", new=_run_web_client):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.sleep(0)
            state = app.extensions["mugen"]["bootstrap"]
            state[SHUTDOWN_REQUESTED_KEY] = True
            trigger.set()
            await runner

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["web"], PHASE_STATUS_STOPPED)

    async def test_run_platform_clients_surfaces_runner_error_when_shutdown_requested(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        started = asyncio.Event()
        release = asyncio.Event()

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = (degraded_callback, healthy_callback)
            if callable(started_callback):
                started_callback()
            started.set()
            await release.wait()
            raise ValueError("late failure")

        with unittest.mock.patch("mugen.run_web_client", new=_run_web_client):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1.0)
            state = app.extensions["mugen"]["bootstrap"]
            state[SHUTDOWN_REQUESTED_KEY] = True
            release.set()
            await runner

        state = app.extensions["mugen"]["bootstrap"]
        self.assertIn(
            "RuntimeError: ValueError: late failure",
            str(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"]),
        )

    async def test_run_platform_clients_handles_cancellation(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["whatsapp"])
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

    async def test_run_platform_clients_marks_whatsapp_degraded_when_shutdown_cleanup_fails(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["whatsapp"])
        started = asyncio.Event()

        async def _cancel_to_runtime_error(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = degraded_callback
            _ = healthy_callback
            if callable(started_callback):
                started_callback()
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError as exc:
                raise RuntimeError(
                    "WhatsApp client shutdown failed during cancellation: "
                    "RuntimeError: close failed"
                ) from exc

        with unittest.mock.patch(
            target="mugen.run_whatsapp_client",
            new=_cancel_to_runtime_error,
        ):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                    whatsapp_provider=lambda: None,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1.0)
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(
            state[PHASE_B_PLATFORM_STATUSES_KEY]["whatsapp"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertIn(
            "shutdown failed during cancellation",
            str(state[PHASE_B_PLATFORM_ERRORS_KEY]["whatsapp"]),
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)

    async def test_run_platform_clients_rejects_telnet_platform(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["telnet"])

        with self.assertRaises(BootstrapConfigError):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

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

    def test_line_provider_reads_di_container(self) -> None:
        sentinel_client = object()
        with unittest.mock.patch.object(
            mugen_mod.di,
            "container",
            SimpleNamespace(line_client=sentinel_client),
        ):
            self.assertIs(
                mugen_mod._line_provider(),  # pylint: disable=protected-access
                sentinel_client,
            )

    def test_signal_provider_reads_di_container(self) -> None:
        sentinel_client = object()
        with unittest.mock.patch.object(
            mugen_mod.di,
            "container",
            SimpleNamespace(signal_client=sentinel_client),
        ):
            self.assertIs(
                mugen_mod._signal_provider(),  # pylint: disable=protected-access
                sentinel_client,
            )

    def test_wechat_provider_reads_di_container(self) -> None:
        sentinel_client = object()
        with unittest.mock.patch.object(
            mugen_mod.di,
            "container",
            SimpleNamespace(wechat_client=sentinel_client),
        ):
            self.assertIs(
                mugen_mod._wechat_provider(),  # pylint: disable=protected-access
                sentinel_client,
            )

    def test_runtime_provider_helpers_read_di_container(self) -> None:
        sentinel_logger = object()
        sentinel_ipc = object()
        sentinel_messaging = object()
        sentinel_platform = object()
        with unittest.mock.patch.object(
            mugen_mod.di,
            "container",
            SimpleNamespace(
                logging_gateway=sentinel_logger,
                ipc_service=sentinel_ipc,
                messaging_service=sentinel_messaging,
                platform_service=sentinel_platform,
            ),
        ):
            self.assertIs(
                mugen_mod._logger_provider(),  # pylint: disable=protected-access
                sentinel_logger,
            )
            self.assertIs(
                mugen_mod._ipc_provider(),  # pylint: disable=protected-access
                sentinel_ipc,
            )
            self.assertIs(
                mugen_mod._messaging_provider(),  # pylint: disable=protected-access
                sentinel_messaging,
            )
            self.assertIs(
                mugen_mod._platform_provider(),  # pylint: disable=protected-access
                sentinel_platform,
            )

    async def test_bootstrap_app_registers_extensions_and_api_blueprint(self) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=[])
        register_extensions_mock = unittest.mock.AsyncMock()
        readiness_mock = unittest.mock.AsyncMock()

        with unittest.mock.patch.object(
            mugen_mod,
            "register_extensions",
            new=register_extensions_mock,
        ), unittest.mock.patch.object(
            mugen_mod.di,
            "ensure_container_readiness_async",
            new=readiness_mock,
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        readiness_mock.assert_awaited_once()
        register_extensions_mock.assert_awaited_once()
        self.assertIn("api", app.blueprints)
        self.assertIs(app.blueprints["api"], mugen_mod.api)

    async def test_bootstrap_app_marks_blocking_failure_when_config_unavailable(
        self,
    ) -> None:
        app = Quart("test_app")

        with self.assertRaisesRegex(BootstrapConfigError, "Configuration unavailable"):
            await bootstrap_app(
                app,
                config_provider=lambda: (_ for _ in ()).throw(RuntimeError("cfg down")),
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        errors = state[mugen_mod.PHASE_A_CAPABILITY_ERRORS_KEY]
        self.assertEqual(
            statuses["container_configuration"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertEqual(errors["container_configuration"], "cfg down")
        self.assertEqual(
            state[mugen_mod.PHASE_A_BLOCKING_FAILURES_KEY],
            ["container_configuration"],
        )
        self.assertEqual(state[mugen_mod.PHASE_A_NON_BLOCKING_DEGRADATIONS_KEY], [])
        self.assertEqual(state[mugen_mod.PHASE_A_ERROR_KEY], "Configuration unavailable.")

    async def test_bootstrap_app_fails_fast_when_provider_readiness_fails(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=[])
        register_extensions_mock = unittest.mock.AsyncMock()

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(
                    side_effect=mugen_mod.di.ProviderBootstrapError("provider down")
                ),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=register_extensions_mock,
            ),
            self.assertRaises(BootstrapConfigError),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
                logger_provider=lambda: app.logger,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(
            state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]["container_readiness"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertIn("provider down", str(state[mugen_mod.PHASE_A_ERROR_KEY]))
        register_extensions_mock.assert_not_awaited()

    async def test_bootstrap_app_fails_when_active_platform_lacks_mh_capability(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["matrix"], mh_mode="required")
        register_extensions_mock = unittest.mock.AsyncMock(return_value={})

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=register_extensions_mock,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(mh_extensions=[]),
            ),
            self.assertRaises(BootstrapConfigError),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        errors = state[mugen_mod.PHASE_A_CAPABILITY_ERRORS_KEY]
        self.assertEqual(statuses["messaging.mh.matrix"], PHASE_STATUS_DEGRADED)
        self.assertIn(
            "mugen.messaging.mh_mode='required'",
            errors["messaging.mh.matrix"],
        )

    async def test_bootstrap_app_allows_zero_mh_when_mode_is_optional(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["web"], mh_mode="optional")
        register_extensions_mock = unittest.mock.AsyncMock(
            return_value={"fw": ["core.fw.acp", "core.fw.web"]}
        )

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=register_extensions_mock,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(
                    mh_extensions=[],
                ),
            ),
            unittest.mock.patch.object(mugen_mod, "_web_provider", return_value=object()),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(statuses["messaging.mh.mode"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["messaging.mh.availability"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["messaging.mh.web"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["web.fw.extension_contract"], PHASE_STATUS_HEALTHY)

    async def test_bootstrap_app_fails_when_web_fw_contract_tokens_missing(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["web"], mh_mode="optional")

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={"fw": ["core.fw.web"]}),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(mh_extensions=[]),
            ),
            unittest.mock.patch.object(mugen_mod, "_web_provider", return_value=object()),
            self.assertRaisesRegex(
                BootstrapConfigError,
                "web.fw.extension_contract",
            ),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        errors = state[mugen_mod.PHASE_A_CAPABILITY_ERRORS_KEY]
        self.assertEqual(statuses["web.fw.extension_contract"], PHASE_STATUS_DEGRADED)
        self.assertIn("core.fw.acp", errors["web.fw.extension_contract"])

    async def test_bootstrap_app_fails_when_line_extension_contract_tokens_missing(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["line"], mh_mode="optional")

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={"fw": [], "ipc": []}),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(mh_extensions=[]),
            ),
            unittest.mock.patch.object(mugen_mod, "_line_provider", return_value=object()),
            self.assertRaisesRegex(
                BootstrapConfigError,
                "line.fw.extension_contract",
            ),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(
            statuses["line.fw.extension_contract"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertEqual(
            statuses["line.ipc.extension_contract"],
            PHASE_STATUS_DEGRADED,
        )

    async def test_bootstrap_app_marks_line_capabilities_healthy_when_satisfied(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["line"], mh_mode="required")
        register_extensions_mock = unittest.mock.AsyncMock(
            return_value={
                "fw": ["core.fw.line_messagingapi"],
                "ipc": ["core.ipc.line_messagingapi"],
            }
        )

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=register_extensions_mock,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(
                    mh_extensions=[SimpleNamespace(platforms=["line"])]
                ),
            ),
            unittest.mock.patch.object(mugen_mod, "_line_provider", return_value=object()),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(statuses["line.client_runtime_path"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["line.fw.extension_contract"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["line.ipc.extension_contract"], PHASE_STATUS_HEALTHY)

    async def test_bootstrap_app_fails_when_signal_extension_contract_tokens_missing(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["signal"], mh_mode="optional")

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={"fw": [], "ipc": []}),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(mh_extensions=[]),
            ),
            unittest.mock.patch.object(mugen_mod, "_signal_provider", return_value=object()),
            self.assertRaisesRegex(
                BootstrapConfigError,
                "signal.ipc.extension_contract",
            ),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(
            statuses["signal.ipc.extension_contract"],
            PHASE_STATUS_DEGRADED,
        )

    async def test_bootstrap_app_marks_signal_capabilities_healthy_when_satisfied(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["signal"], mh_mode="required")
        register_extensions_mock = unittest.mock.AsyncMock(
            return_value={
                "fw": [],
                "ipc": ["core.ipc.signal_restapi"],
            }
        )

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=register_extensions_mock,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(
                    mh_extensions=[SimpleNamespace(platforms=["signal"])]
                ),
            ),
            unittest.mock.patch.object(mugen_mod, "_signal_provider", return_value=object()),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(statuses["signal.client_runtime_path"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["signal.ipc.extension_contract"], PHASE_STATUS_HEALTHY)

    async def test_bootstrap_app_fails_when_telegram_extension_contract_tokens_missing(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["telegram"], mh_mode="optional")

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={"fw": [], "ipc": []}),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(mh_extensions=[]),
            ),
            unittest.mock.patch.object(mugen_mod, "_telegram_provider", return_value=object()),
            self.assertRaisesRegex(
                BootstrapConfigError,
                "telegram.fw.extension_contract",
            ),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(
            statuses["telegram.fw.extension_contract"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertEqual(
            statuses["telegram.ipc.extension_contract"],
            PHASE_STATUS_DEGRADED,
        )

    async def test_bootstrap_app_marks_telegram_capabilities_healthy_when_satisfied(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["telegram"], mh_mode="required")
        register_extensions_mock = unittest.mock.AsyncMock(
            return_value={
                "fw": ["core.fw.telegram_botapi"],
                "ipc": ["core.ipc.telegram_botapi"],
            }
        )

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=register_extensions_mock,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(
                    mh_extensions=[SimpleNamespace(platforms=["telegram"])]
                ),
            ),
            unittest.mock.patch.object(mugen_mod, "_telegram_provider", return_value=object()),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(statuses["telegram.client_runtime_path"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["telegram.fw.extension_contract"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["telegram.ipc.extension_contract"], PHASE_STATUS_HEALTHY)

    async def test_bootstrap_app_fails_when_wechat_extension_contract_tokens_missing(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["wechat"], mh_mode="optional")

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={"fw": [], "ipc": []}),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(mh_extensions=[]),
            ),
            unittest.mock.patch.object(mugen_mod, "_wechat_provider", return_value=object()),
            self.assertRaisesRegex(
                BootstrapConfigError,
                "wechat.fw.extension_contract",
            ),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(
            statuses["wechat.fw.extension_contract"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertEqual(
            statuses["wechat.ipc.extension_contract"],
            PHASE_STATUS_DEGRADED,
        )

    async def test_bootstrap_app_marks_wechat_capabilities_healthy_when_satisfied(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["wechat"], mh_mode="required")
        register_extensions_mock = unittest.mock.AsyncMock(
            return_value={
                "fw": ["core.fw.wechat"],
                "ipc": ["core.ipc.wechat"],
            }
        )

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=register_extensions_mock,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(
                    mh_extensions=[SimpleNamespace(platforms=["wechat"])]
                ),
            ),
            unittest.mock.patch.object(mugen_mod, "_wechat_provider", return_value=object()),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(statuses["wechat.client_runtime_path"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["wechat.fw.extension_contract"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["wechat.ipc.extension_contract"], PHASE_STATUS_HEALTHY)

    async def test_bootstrap_app_marks_required_capabilities_healthy_when_satisfied(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["web", "matrix"], mh_mode="required")
        register_extensions_mock = unittest.mock.AsyncMock(
            return_value={"fw": ["core.fw.acp", "core.fw.web"]}
        )

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=register_extensions_mock,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(
                    mh_extensions=[SimpleNamespace(platforms=[])]
                ),
            ),
            unittest.mock.patch.object(mugen_mod, "_web_provider", return_value=object()),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        state = app.extensions["mugen"]["bootstrap"]
        statuses = state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY]
        self.assertEqual(statuses["messaging.mh.web"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["messaging.mh.matrix"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["messaging.mh.mode"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["messaging.mh.availability"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["web.client_runtime_path"], PHASE_STATUS_HEALTHY)
        self.assertEqual(statuses["web.fw.extension_contract"], PHASE_STATUS_HEALTHY)

    async def test_bootstrap_app_passes_optional_provider_failures_to_capability_eval(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["matrix"], mh_mode="optional")
        captured_input = {}

        def _capture_capability_input(capability_input):
            captured_input["value"] = capability_input
            return SimpleNamespace(
                statuses={},
                errors={},
                failed_capabilities=[],
                non_blocking_degraded_capabilities=[],
                healthy=True,
            )

        readiness_report = mugen_mod.di.ProviderReadinessReport(
            successful_providers=("completion_gateway",),
            required_failures={},
            optional_failures={"email_gateway": "smtp unavailable"},
        )

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod.di,
                "get_container_readiness_report",
                return_value=readiness_report,
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={}),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "evaluate_runtime_capabilities",
                side_effect=_capture_capability_input,
            ),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        runtime_input = captured_input["value"]
        self.assertEqual(
            runtime_input.optional_provider_failures,
            {"email_gateway": "smtp unavailable"},
        )
        self.assertEqual(runtime_input.registered_fw_extension_tokens, [])
        self.assertEqual(runtime_input.registered_ipc_extension_tokens, [])

    async def test_bootstrap_app_normalizes_non_dict_phase_a_capability_state(self) -> None:
        app = Quart("test_app")
        state = app.extensions.setdefault("mugen", {}).setdefault("bootstrap", {})
        state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY] = "invalid"
        state[mugen_mod.PHASE_A_CAPABILITY_ERRORS_KEY] = "invalid"
        cfg = _test_config(platforms=[])

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={}),
            ),
            unittest.mock.patch.object(mugen_mod, "_messaging_provider", return_value=None),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        self.assertIsInstance(state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY], dict)
        self.assertIsInstance(state[mugen_mod.PHASE_A_CAPABILITY_ERRORS_KEY], dict)

    async def test_bootstrap_app_reuses_existing_phase_a_capability_dict_state(self) -> None:
        app = Quart("test_app")
        state = app.extensions.setdefault("mugen", {}).setdefault("bootstrap", {})
        existing_statuses = {"seed": PHASE_STATUS_HEALTHY}
        existing_errors = {"seed": None}
        state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY] = existing_statuses
        state[mugen_mod.PHASE_A_CAPABILITY_ERRORS_KEY] = existing_errors
        cfg = _test_config(platforms=[])

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={}),
            ),
            unittest.mock.patch.object(mugen_mod, "_messaging_provider", return_value=None),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

        self.assertIs(state[mugen_mod.PHASE_A_CAPABILITY_STATUSES_KEY], existing_statuses)
        self.assertIs(state[mugen_mod.PHASE_A_CAPABILITY_ERRORS_KEY], existing_errors)
        self.assertEqual(existing_statuses["container_readiness"], PHASE_STATUS_HEALTHY)

    async def test_bootstrap_app_handles_non_dict_extension_report_and_non_list_handlers(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=["matrix"], mh_mode="required")

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value="invalid-report"),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "_messaging_provider",
                return_value=SimpleNamespace(mh_extensions="invalid"),
            ),
            self.assertRaises(BootstrapConfigError),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

    async def test_bootstrap_app_uses_fallback_message_for_missing_capability_reason(
        self,
    ) -> None:
        app = Quart("test_app")
        cfg = _test_config(platforms=[])

        fake_result = SimpleNamespace(
            statuses={"container_readiness": PHASE_STATUS_HEALTHY},
            errors={"missing": None},
            failed_capabilities=["missing"],
            non_blocking_degraded_capabilities=[],
            healthy=False,
        )

        with (
            unittest.mock.patch.object(
                mugen_mod.di,
                "ensure_container_readiness_async",
                new=unittest.mock.AsyncMock(),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "register_extensions",
                new=unittest.mock.AsyncMock(return_value={}),
            ),
            unittest.mock.patch.object(
                mugen_mod,
                "evaluate_runtime_capabilities",
                return_value=fake_result,
            ),
            self.assertRaisesRegex(BootstrapConfigError, "capability unavailable"),
        ):
            await bootstrap_app(
                app,
                config_provider=lambda: cfg,
            )

    def test_resolve_messaging_mh_mode_handles_dict_and_namespace_paths(self) -> None:
        self.assertEqual(
            mugen_mod._resolve_messaging_mh_mode(  # pylint: disable=protected-access
                {"mugen": {"messaging": {"mh_mode": "optional"}}}
            ),
            "optional",
        )
        self.assertEqual(
            mugen_mod._resolve_messaging_mh_mode(  # pylint: disable=protected-access
                SimpleNamespace(
                    mugen=SimpleNamespace(
                        messaging={"mh_mode": "required"},
                    )
                )
            ),
            "required",
        )
        with self.assertRaises(BootstrapConfigError):
            mugen_mod._resolve_messaging_mh_mode(  # pylint: disable=protected-access
                {"mugen": {"messaging": {"mh_mode": "legacy"}}}
            )
        with self.assertRaises(BootstrapConfigError):
            mugen_mod._resolve_messaging_mh_mode(  # pylint: disable=protected-access
                SimpleNamespace()
            )

    def test_platform_state_helpers_cover_edge_branches(self) -> None:
        self.assertTrue(
            mugen_mod._parse_bool("yes", default=False)  # pylint: disable=protected-access
        )
        self.assertFalse(
            mugen_mod._parse_bool("OFF", default=True)  # pylint: disable=protected-access
        )
        self.assertTrue(
            mugen_mod._parse_bool("maybe", default=True)  # pylint: disable=protected-access
        )
        self.assertEqual(
            mugen_mod._normalize_extension_token_list(  # pylint: disable=protected-access
                "bad"
            ),
            [],
        )
        self.assertEqual(
            mugen_mod._normalize_extension_token_list(  # pylint: disable=protected-access
                ["core.fw.web", "", " CORE.FW.WEB ", 1]
            ),
            ["core.fw.web"],
        )
        self.assertEqual(
            mugen_mod._resolve_registered_ipc_extension_tokens(  # pylint: disable=protected-access
                {"ipc": ["core.ipc.telegram_botapi", "", " CORE.IPC.TELEGRAM_BOTAPI ", 1]}
            ),
            ["core.ipc.telegram_botapi"],
        )
        self.assertEqual(
            mugen_mod._normalize_platform_list([" web ", "", "web", "matrix"]),  # pylint: disable=protected-access
            ["web", "matrix"],
        )
        self.assertEqual(  # pylint: disable=protected-access
            mugen_mod._coerce_positive_int(-1, default=3),
            3,
        )
        self.assertEqual(  # pylint: disable=protected-access
            mugen_mod._coerce_positive_int("bad", default=4),
            4,
        )
        self.assertEqual(  # pylint: disable=protected-access
            mugen_mod._resolve_supervisor_backoff_seconds(
                None,
                field_name="field",
                default=1.5,
            ),
            1.5,
        )
        with self.assertRaisesRegex(RuntimeError, "field"):
            mugen_mod._resolve_supervisor_backoff_seconds(  # pylint: disable=protected-access
                0.0,
                field_name="field",
                default=1.5,
            )
        self.assertIsNone(
            mugen_mod._read_optional_attr(  # pylint: disable=protected-access
                None,
                "missing",
                default=None,
            )
        )
        self.assertFalse(
            mugen_mod._config_path_exists(  # pylint: disable=protected-access
                {"mugen": None},
                "mugen",
                "modules",
            )
        )
        self.assertFalse(
            mugen_mod._config_path_exists(  # pylint: disable=protected-access
                {"mugen": {}},
                "mugen",
                "modules",
            )
        )

        class _SlotNode:
            __slots__ = ("child",)

        slot_root = _SlotNode()
        slot_child = _SlotNode()
        slot_root.child = slot_child
        slot_child.child = None
        self.assertTrue(
            mugen_mod._config_path_exists(slot_root, "child")  # pylint: disable=protected-access
        )
        self.assertFalse(
            mugen_mod._config_path_exists(slot_root, "missing")  # pylint: disable=protected-access
        )
        dict_backed = SimpleNamespace(existing=SimpleNamespace())
        self.assertFalse(
            mugen_mod._config_path_exists(dict_backed, "missing")  # pylint: disable=protected-access
        )

        relational_config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "storage": {
                                "relational": "configured",
                            }
                        }
                    }
                }
            }
        }
        with self.assertRaises(BootstrapConfigError):
            mugen_mod.validate_web_relational_runtime_config(
                config=relational_config,
                active_platforms=["web"],
                relational_storage_gateway_provider=lambda: None,
            )
        with self.assertRaises(BootstrapConfigError):
            mugen_mod.validate_web_relational_runtime_config(
                config={"mugen": {"modules": {"core": {"gateway": {"storage": {}}}}}},
                active_platforms=["web"],
                relational_storage_gateway_provider=lambda: object(),
            )

        class _ReadyRelational:  # pylint: disable=too-few-public-methods
            def check_readiness(self) -> None:
                return None

        with self.assertRaises(BootstrapConfigError):
            mugen_mod.validate_web_relational_runtime_config(
                config=relational_config,
                active_platforms=["web"],
                relational_storage_gateway_provider=lambda: _ReadyRelational(),
                web_runtime_store_provider=lambda: object(),
            )

        web_runtime_config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "storage": {
                                "relational": "configured",
                                "web_runtime": "configured",
                            }
                        }
                    }
                }
            }
        }
        with self.assertRaises(BootstrapConfigError):
            mugen_mod.validate_web_relational_runtime_config(
                config=web_runtime_config,
                active_platforms=["web"],
                relational_storage_gateway_provider=lambda: _ReadyRelational(),
                web_runtime_store_provider=lambda: None,
            )
        with self.assertRaises(BootstrapConfigError):
            mugen_mod.validate_web_relational_runtime_config(
                config=web_runtime_config,
                active_platforms=["web"],
                relational_storage_gateway_provider=lambda: _ReadyRelational(),
                web_runtime_store_provider=lambda: object(),
            )

        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(
                    profile="platform_full",
                    provider_readiness_timeout_seconds=15.0,
                    provider_shutdown_timeout_seconds=10.0,
                    shutdown_timeout_seconds=60.0,
                    phase_b=SimpleNamespace(
                        startup_timeout_seconds=30.0,
                        critical_platforms=[" web ", "", "matrix"],
                    ),
                )
            )
        )
        state: dict[str, object] = {}
        self.assertEqual(
            mugen_mod._resolve_phase_b_critical_platforms(  # pylint: disable=protected-access
                config,
                state,
                active_platforms=["web"],
            ),
            ["web", "matrix"],
        )
        state["phase_b_critical_platforms"] = [" whatsapp "]
        self.assertEqual(
            mugen_mod._resolve_phase_b_critical_platforms(  # pylint: disable=protected-access
                config,
                state,
                active_platforms=["web"],
            ),
            ["whatsapp"],
        )

        state = {
            PHASE_B_PLATFORM_STATUSES_KEY: "invalid",
            PHASE_B_PLATFORM_ERRORS_KEY: "invalid",
        }
        mugen_mod._set_platform_status(  # pylint: disable=protected-access
            state,
            platform="web",
            status=PHASE_STATUS_HEALTHY,
            error=None,
        )
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["web"], PHASE_STATUS_HEALTHY)
        self.assertIsNone(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"])

        # Empty/non-dict state normalizes to healthy when no platforms are active.
        state = {
            PHASE_B_PLATFORM_STATUSES_KEY: "invalid",
            PHASE_B_PLATFORM_ERRORS_KEY: "invalid",
        }
        mugen_mod._refresh_phase_b_status(  # pylint: disable=protected-access
            state,
            critical_platforms=[],
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)

        controls_cfg = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(
                    phase_b=SimpleNamespace(
                        supervisor_max_restarts=3,
                        supervisor_backoff_base_seconds=5.0,
                        supervisor_backoff_max_seconds=1.0,
                    )
                )
            )
        )
        max_restarts, base_backoff, max_backoff = mugen_mod._resolve_phase_b_supervision_controls(  # pylint: disable=protected-access
            controls_cfg
        )
        self.assertEqual(max_restarts, 3)
        self.assertEqual(base_backoff, 5.0)
        self.assertEqual(max_backoff, 5.0)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

        # Unexpected non-healthy states degrade readiness with explicit reasons.
        state = {
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_STOPPED},
            PHASE_B_PLATFORM_ERRORS_KEY: {"web": None},
        }
        mugen_mod._refresh_phase_b_status(  # pylint: disable=protected-access
            state,
            critical_platforms=["web"],
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn("stopped unexpectedly", str(state[PHASE_B_ERROR_KEY]))

        state = {
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_STARTING},
            PHASE_B_PLATFORM_ERRORS_KEY: {"web": "booting"},
        }
        mugen_mod._refresh_phase_b_status(  # pylint: disable=protected-access
            state,
            critical_platforms=["web"],
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STARTING)

        state = {
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_STOPPED},
            PHASE_B_PLATFORM_ERRORS_KEY: {"web": None},
        }
        mugen_mod._refresh_phase_b_status(  # pylint: disable=protected-access
            state,
            critical_platforms=["web"],
            degrade_on_critical_exit=False,
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)

    async def test_run_platform_clients_marks_stopped_when_shutdown_requested(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["matrix"])
        started = asyncio.Event()
        release = asyncio.Event()

        async def _run_matrix(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = degraded_callback
            _ = healthy_callback
            if callable(started_callback):
                started_callback()
            started.set()
            await release.wait()

        with unittest.mock.patch(target="mugen.run_matrix_client", new=_run_matrix):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1.0)
            state = app.extensions["mugen"]["bootstrap"]
            state[SHUTDOWN_REQUESTED_KEY] = True
            release.set()
            await runner

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["matrix"], PHASE_STATUS_STOPPED)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STOPPED)

    async def test_run_platform_clients_marks_noncritical_clean_exit_as_stopped(self) -> None:
        app = Quart("test_app")
        state = app.extensions.setdefault("mugen", {}).setdefault("bootstrap", {})
        state["phase_b_critical_platforms"] = ["web"]
        state["phase_b_degrade_on_critical_exit"] = False
        config = _test_config(platforms=["web"])

        with unittest.mock.patch(
            target="mugen.run_web_client",
            new=unittest.mock.AsyncMock(),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["web"], PHASE_STATUS_DEGRADED)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)

    async def test_run_platform_clients_raises_on_invalid_critical_platform(self) -> None:
        app = Quart("test_app")
        state = app.extensions.setdefault("mugen", {}).setdefault("bootstrap", {})
        state["phase_b_critical_platforms"] = ["not-enabled"]
        config = _test_config(platforms=["web"])

        with self.assertRaises(BootstrapConfigError):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_run_platform_clients_raises_on_unknown_active_platform(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web", "unknown"])

        with self.assertRaises(BootstrapConfigError):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_run_platform_clients_raises_on_known_but_inactive_critical_platform(
        self,
    ) -> None:
        app = Quart("test_app")
        state = app.extensions.setdefault("mugen", {}).setdefault("bootstrap", {})
        state["phase_b_critical_platforms"] = ["matrix"]
        config = _test_config(platforms=["web"])

        with self.assertRaises(BootstrapConfigError):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_run_platform_clients_raises_on_relational_web_miswire(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        config.mugen.modules = SimpleNamespace(
            core=SimpleNamespace(
                gateway=SimpleNamespace(
                    storage=SimpleNamespace(relational="configured"),
                )
            )
        )

        with self.assertRaises(BootstrapConfigError):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                relational_storage_gateway_provider=lambda: object(),
            )

    async def test_run_platform_clients_marks_platform_degraded_on_exception(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])

        async def _boom(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            raise RuntimeError("worker failure")

        with unittest.mock.patch(target="mugen.run_web_client", new=_boom):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["web"], PHASE_STATUS_DEGRADED)
        self.assertIn("RuntimeError: worker failure", state[PHASE_B_PLATFORM_ERRORS_KEY]["web"])

    async def test_run_platform_clients_marks_whatsapp_degraded_when_startup_probe_fails(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["whatsapp"])

        async def _probe_fail(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            raise RuntimeError("WhatsApp startup probe failed.")

        with unittest.mock.patch("mugen.run_whatsapp_client", new=_probe_fail):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
                whatsapp_provider=lambda: None,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(
            state[PHASE_B_PLATFORM_STATUSES_KEY]["whatsapp"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertIn(
            "WhatsApp startup probe failed.",
            str(state[PHASE_B_PLATFORM_ERRORS_KEY]["whatsapp"]),
        )

    async def test_run_whatsapp_client_attempts_cleanup_when_init_fails(self) -> None:
        logger = unittest.mock.Mock()
        whatsapp_client = unittest.mock.Mock()
        whatsapp_client.init = unittest.mock.AsyncMock(
            side_effect=RuntimeError("init failed")
        )
        whatsapp_client.verify_startup = unittest.mock.AsyncMock()
        whatsapp_client.close = unittest.mock.AsyncMock()
        degraded_callback = unittest.mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "init failed"):
            await run_whatsapp_client(
                logger_provider=lambda: logger,
                whatsapp_provider=lambda: whatsapp_client,
                degraded_callback=degraded_callback,
            )

        whatsapp_client.close.assert_awaited_once()
        degraded_callback.assert_called_once()

    async def test_run_whatsapp_client_attempts_cleanup_when_startup_probe_fails(
        self,
    ) -> None:
        logger = unittest.mock.Mock()
        whatsapp_client = unittest.mock.Mock()
        whatsapp_client.init = unittest.mock.AsyncMock(return_value=None)
        whatsapp_client.verify_startup = unittest.mock.AsyncMock(return_value=False)
        whatsapp_client.close = unittest.mock.AsyncMock()
        degraded_callback = unittest.mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "WhatsApp startup probe failed"):
            await run_whatsapp_client(
                logger_provider=lambda: logger,
                whatsapp_provider=lambda: whatsapp_client,
                degraded_callback=degraded_callback,
            )

        whatsapp_client.close.assert_awaited_once()
        degraded_callback.assert_called_once()

    async def test_run_whatsapp_client_preserves_primary_error_when_cleanup_fails(
        self,
    ) -> None:
        logger = unittest.mock.Mock()
        whatsapp_client = unittest.mock.Mock()
        whatsapp_client.init = unittest.mock.AsyncMock(
            side_effect=RuntimeError("init failed")
        )
        whatsapp_client.verify_startup = unittest.mock.AsyncMock()
        whatsapp_client.close = unittest.mock.AsyncMock(
            side_effect=RuntimeError("close failed")
        )
        degraded_callback = unittest.mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "init failed"):
            await run_whatsapp_client(
                logger_provider=lambda: logger,
                whatsapp_provider=lambda: whatsapp_client,
                degraded_callback=degraded_callback,
            )

        degraded_callback.assert_called_once()
        whatsapp_client.close.assert_awaited_once()
        logger.error.assert_called_once()
        self.assertIn("WhatsApp client shutdown failed", logger.error.call_args.args[0])

    async def test_run_platform_clients_tracks_whatsapp_runtime_degrade_and_recover(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["whatsapp"])
        degraded = asyncio.Event()
        recover = asyncio.Event()
        release = asyncio.Event()

        async def _run_whatsapp_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            if callable(started_callback):
                started_callback()
            if callable(degraded_callback):
                degraded_callback("RuntimeError: probe failed")
            degraded.set()
            await recover.wait()
            if callable(healthy_callback):
                healthy_callback()
            await release.wait()

        with unittest.mock.patch("mugen.run_whatsapp_client", new=_run_whatsapp_client):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.wait_for(degraded.wait(), timeout=1.0)
            await asyncio.sleep(0)
            state = app.extensions["mugen"]["bootstrap"]
            self.assertEqual(
                state[PHASE_B_PLATFORM_STATUSES_KEY]["whatsapp"],
                PHASE_STATUS_DEGRADED,
            )
            self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)

            recover.set()
            await asyncio.sleep(0)
            self.assertEqual(
                state[PHASE_B_PLATFORM_STATUSES_KEY]["whatsapp"],
                PHASE_STATUS_HEALTHY,
            )
            self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)

            runner.cancel()
            with self.assertRaises(asyncio.exceptions.CancelledError):
                await runner

    async def test_run_platform_clients_tracks_matrix_runtime_degrade_and_recover(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["matrix"])
        degraded = asyncio.Event()
        recover = asyncio.Event()
        release = asyncio.Event()

        async def _run_matrix_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            if callable(started_callback):
                started_callback()
            if callable(degraded_callback):
                degraded_callback("RuntimeError: sync failed")
            degraded.set()
            await recover.wait()
            if callable(healthy_callback):
                healthy_callback()
            await release.wait()

        with unittest.mock.patch("mugen.run_matrix_client", new=_run_matrix_client):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.wait_for(degraded.wait(), timeout=1.0)
            await asyncio.sleep(0)
            state = app.extensions["mugen"]["bootstrap"]
            self.assertEqual(
                state[PHASE_B_PLATFORM_STATUSES_KEY]["matrix"],
                PHASE_STATUS_DEGRADED,
            )
            self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)

            recover.set()
            await asyncio.sleep(0)
            self.assertEqual(
                state[PHASE_B_PLATFORM_STATUSES_KEY]["matrix"],
                PHASE_STATUS_HEALTHY,
            )
            self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)

            runner.cancel()
            with self.assertRaises(asyncio.exceptions.CancelledError):
                await runner

    async def test_run_platform_clients_keeps_web_starting_until_started_callback(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])
        allow_start = asyncio.Event()
        keep_running = asyncio.Event()

        async def _run_web_client(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = degraded_callback
            _ = healthy_callback
            await allow_start.wait()
            if callable(started_callback):
                started_callback()
            await keep_running.wait()

        with unittest.mock.patch(
            "mugen.run_web_client",
            new=_run_web_client,
        ):
            runner = asyncio.create_task(
                run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )
            )
            await asyncio.sleep(0)
            state = app.extensions["mugen"]["bootstrap"]
            self.assertEqual(
                state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
                PHASE_STATUS_STARTING,
            )

            allow_start.set()
            await asyncio.sleep(0)
            self.assertEqual(
                state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
                PHASE_STATUS_HEALTHY,
            )

            runner.cancel()
            with self.assertRaises(asyncio.exceptions.CancelledError):
                await runner

    async def test_run_platform_clients_marks_web_degraded_on_bind_failure(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["web"])

        async def _fail_web(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            raise OSError("address already in use")

        with unittest.mock.patch("mugen.run_web_client", new=_fail_web):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(
            state[PHASE_B_PLATFORM_STATUSES_KEY]["web"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertIn(
            "OSError: address already in use",
            str(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"]),
        )

    async def test_run_platform_clients_raises_config_error_on_task_creation_attribute_error(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["matrix"])

        def _raise_attr_error(coro, *_args, **_kwargs):
            coro.close()
            raise AttributeError("bad")

        with unittest.mock.patch("mugen.asyncio.create_task", new=_raise_attr_error):
            with self.assertRaises(BootstrapConfigError):
                await run_platform_clients(
                    app,
                    config_provider=lambda: config,
                    logger_provider=lambda: app.logger,
                )

    async def test_run_platform_clients_returns_when_no_platforms_enabled(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=[])
        await run_platform_clients(
            app,
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
        )
        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)

    async def test_run_platform_clients_cancellation_skips_done_tasks(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["matrix", "web"])

        async def _fast_matrix(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            return

        async def _slow_web(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            await asyncio.Event().wait()

        async def _cancel_wait(*_args, **_kwargs):
            await asyncio.sleep(0)
            raise asyncio.exceptions.CancelledError()

        with (
            unittest.mock.patch("mugen.run_matrix_client", new=_fast_matrix),
            unittest.mock.patch("mugen.run_web_client", new=_slow_web),
            unittest.mock.patch("mugen.asyncio.wait", new=_cancel_wait),
            self.assertRaises(asyncio.exceptions.CancelledError),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_run_platform_clients_removes_multiple_finished_tasks(self) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["matrix", "web"])

        async def _fast_matrix(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            return

        async def _fast_web(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            return

        async def _wait_all(tasks, **_kwargs):
            return set(tasks), set()

        with (
            unittest.mock.patch("mugen.run_matrix_client", new=_fast_matrix),
            unittest.mock.patch("mugen.run_web_client", new=_fast_web),
            unittest.mock.patch("mugen.asyncio.wait", new=_wait_all),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_run_platform_clients_handles_unmatched_finished_task_in_wait_set(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _test_config(platforms=["matrix"])
        call_count = 0
        foreign_task = asyncio.create_task(asyncio.sleep(0))

        async def _fast_matrix(
            *,
            started_callback=None,
            degraded_callback=None,
            healthy_callback=None,
        ) -> None:
            _ = started_callback
            _ = degraded_callback
            _ = healthy_callback
            return

        async def _wait_with_foreign(_tasks, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {foreign_task}, set()
            raise asyncio.exceptions.CancelledError()

        with (
            unittest.mock.patch("mugen.run_matrix_client", new=_fast_matrix),
            unittest.mock.patch("mugen.asyncio.wait", new=_wait_with_foreign),
            self.assertRaises(asyncio.exceptions.CancelledError),
        ):
            await run_platform_clients(
                app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        await asyncio.gather(foreign_task, return_exceptions=True)
