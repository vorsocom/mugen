"""Provides unit tests for mugen.run_clients."""

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
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STOPPED,
    PHASE_STATUS_STARTING,
    SHUTDOWN_REQUESTED_KEY,
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

    async def test_run_platform_clients_marks_phase_b_degraded_on_critical_exit(self) -> None:
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
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn("matrix", str(state[PHASE_B_ERROR_KEY]))
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["matrix"], PHASE_STATUS_DEGRADED)
        self.assertIsNotNone(state[PHASE_B_PLATFORM_ERRORS_KEY]["matrix"])

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
            mugen_mod._normalize_platform_list([" web ", "", "web", "matrix"]),  # pylint: disable=protected-access
            ["web", "matrix"],
        )

        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(
                    phase_b=SimpleNamespace(critical_platforms=[" web ", "", "matrix"])
                )
            )
        )
        state: dict[str, object] = {}
        self.assertEqual(
            mugen_mod._resolve_phase_b_critical_platforms(  # pylint: disable=protected-access
                config,
                state,
                active_platforms=["telnet"],
            ),
            ["web", "matrix"],
        )
        state["phase_b_critical_platforms"] = [" whatsapp "]
        self.assertEqual(
            mugen_mod._resolve_phase_b_critical_platforms(  # pylint: disable=protected-access
                config,
                state,
                active_platforms=["telnet"],
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

    async def test_run_platform_clients_marks_stopped_when_shutdown_requested(
        self,
    ) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["matrix"]))
        started = asyncio.Event()
        release = asyncio.Event()

        async def _run_matrix() -> None:
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
        state["phase_b_critical_platforms"] = ["matrix"]
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["web"]))

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
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["web"], PHASE_STATUS_STOPPED)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STARTING)

    async def test_run_platform_clients_marks_platform_degraded_on_exception(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["web"]))

        async def _boom() -> None:
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

    async def test_run_platform_clients_raises_config_error_on_task_creation_attribute_error(
        self,
    ) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["matrix"]))

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
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=[]))
        await run_platform_clients(
            app,
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
        )
        state = app.extensions["mugen"]["bootstrap"]
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)

    async def test_run_platform_clients_cancellation_skips_done_tasks(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["matrix", "web"]))

        async def _fast_matrix() -> None:
            return

        async def _slow_web() -> None:
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
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["matrix", "web"]))

        async def _fast_matrix() -> None:
            return

        async def _fast_web() -> None:
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
        config = SimpleNamespace(mugen=SimpleNamespace(platforms=["matrix"]))
        call_count = 0
        foreign_task = asyncio.create_task(asyncio.sleep(0))

        async def _fast_matrix() -> None:
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
