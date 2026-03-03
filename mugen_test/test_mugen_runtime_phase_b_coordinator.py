"""Unit coverage for phase-B startup coordinator edge branches."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mugen.core.runtime import phase_b_coordinator
from mugen.core.runtime.phase_b_bootstrap import PhaseBStartupPlan


class TestPhaseBCoordinator(unittest.TestCase):
    def test_build_startup_plan_requires_timeout(self) -> None:
        startup_plan = PhaseBStartupPlan(
            active_platforms=[],
            critical_platforms=[],
            degrade_on_critical_exit=True,
            readiness_grace_seconds=0.0,
            startup_timeout_seconds=None,
        )
        with patch.object(
            phase_b_coordinator,
            "build_phase_b_startup_plan",
            return_value=startup_plan,
        ):
            with self.assertRaises(RuntimeError):
                phase_b_coordinator._build_startup_plan(  # pylint: disable=protected-access
                    config=object(),
                    bootstrap_state={},
                    logger=object(),
                    validate_phase_b_runtime_config=lambda **_kwargs: ([], [], True),
                    validate_web_relational_runtime_config=lambda **_kwargs: None,
                )

    def test_start_phase_b_runtime_starts_task_and_waits_for_critical_health(
        self,
    ) -> None:
        startup_plan = PhaseBStartupPlan(
            active_platforms=["web"],
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
            readiness_grace_seconds=0.0,
            startup_timeout_seconds=30.0,
        )

        async def _runner(_app) -> None:
            return None

        wait_for_critical_startup = unittest.mock.AsyncMock(return_value=None)

        async def _run() -> tuple[PhaseBStartupPlan, asyncio.Task]:
            with patch.object(
                phase_b_coordinator,
                "prepare_phase_b_startup_plan",
                return_value=startup_plan,
            ):
                return await phase_b_coordinator.start_phase_b_runtime(
                    app=object(),
                    config=object(),
                    bootstrap_state={},
                    logger=object(),
                    run_platform_clients=_runner,
                    wait_for_critical_startup=wait_for_critical_startup,
                    validate_phase_b_runtime_config=lambda **_kwargs: (
                        ["web"],
                        ["web"],
                        True,
                    ),
                    validate_web_relational_runtime_config=lambda **_kwargs: None,
                    task_name="mugen.test.phase_b",
                )

        plan, task = asyncio.run(_run())
        self.assertEqual(plan, startup_plan)
        self.assertEqual(task.get_name(), "mugen.test.phase_b")
        wait_for_critical_startup.assert_awaited_once_with(
            {},
            critical_platforms=["web"],
            startup_timeout_seconds=30.0,
        )

    def test_start_phase_b_runtime_cancels_runner_task_on_wait_failure(self) -> None:
        startup_plan = PhaseBStartupPlan(
            active_platforms=["web"],
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
            readiness_grace_seconds=0.0,
            startup_timeout_seconds=30.0,
        )
        cancellation_seen = {"value": False}
        runner_started = asyncio.Event()

        async def _runner(_app) -> None:
            try:
                runner_started.set()
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen["value"] = True
                raise

        async def _wait_for_critical_startup(*_args, **_kwargs) -> None:
            await runner_started.wait()
            raise RuntimeError("critical startup timeout")

        wait_for_critical_startup = unittest.mock.AsyncMock(
            side_effect=_wait_for_critical_startup
        )

        async def _run() -> None:
            with patch.object(
                phase_b_coordinator,
                "prepare_phase_b_startup_plan",
                return_value=startup_plan,
            ):
                await phase_b_coordinator.start_phase_b_runtime(
                    app=object(),
                    config=object(),
                    bootstrap_state={},
                    logger=object(),
                    run_platform_clients=_runner,
                    wait_for_critical_startup=wait_for_critical_startup,
                    validate_phase_b_runtime_config=lambda **_kwargs: (
                        ["web"],
                        ["web"],
                        True,
                    ),
                    validate_web_relational_runtime_config=lambda **_kwargs: None,
                )

        with self.assertRaisesRegex(RuntimeError, "critical startup timeout"):
            asyncio.run(_run())
        self.assertTrue(cancellation_seen["value"])

    def test_start_phase_b_runtime_rejects_missing_startup_timeout(self) -> None:
        startup_plan = PhaseBStartupPlan(
            active_platforms=["web"],
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
            readiness_grace_seconds=0.0,
            startup_timeout_seconds=None,
        )

        async def _runner(_app) -> None:
            return None

        async def _run() -> None:
            with patch.object(
                phase_b_coordinator,
                "prepare_phase_b_startup_plan",
                return_value=startup_plan,
            ):
                await phase_b_coordinator.start_phase_b_runtime(
                    app=object(),
                    config=object(),
                    bootstrap_state={},
                    logger=object(),
                    run_platform_clients=_runner,
                    wait_for_critical_startup=unittest.mock.AsyncMock(
                        return_value=None
                    ),
                    validate_phase_b_runtime_config=lambda **_kwargs: (
                        ["web"],
                        ["web"],
                        True,
                    ),
                    validate_web_relational_runtime_config=lambda **_kwargs: None,
                )

        with self.assertRaisesRegex(RuntimeError, "startup timeout is required"):
            asyncio.run(_run())

    def test_start_phase_b_runtime_fails_fast_when_cancel_timeout_expires(self) -> None:
        startup_plan = PhaseBStartupPlan(
            active_platforms=["web"],
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
            readiness_grace_seconds=0.0,
            startup_timeout_seconds=30.0,
        )
        runner_started = asyncio.Event()
        cancellation_count = {"value": 0}
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(provider_shutdown_timeout_seconds=0.01)
            )
        )

        async def _runner(_app) -> None:
            runner_started.set()
            while True:
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    cancellation_count["value"] += 1
                    if cancellation_count["value"] >= 2:
                        raise

        async def _wait_for_critical_startup(*_args, **_kwargs) -> None:
            await runner_started.wait()
            raise RuntimeError("critical startup timeout")

        wait_for_critical_startup = unittest.mock.AsyncMock(
            side_effect=_wait_for_critical_startup
        )

        async def _run() -> None:
            with patch.object(
                phase_b_coordinator,
                "prepare_phase_b_startup_plan",
                return_value=startup_plan,
            ):
                await phase_b_coordinator.start_phase_b_runtime(
                    app=object(),
                    config=config,
                    bootstrap_state={},
                    logger=object(),
                    run_platform_clients=_runner,
                    wait_for_critical_startup=wait_for_critical_startup,
                    validate_phase_b_runtime_config=lambda **_kwargs: (
                        ["web"],
                        ["web"],
                        True,
                    ),
                    validate_web_relational_runtime_config=lambda **_kwargs: None,
                )

        with self.assertRaisesRegex(
            RuntimeError,
            "Phase-B runner did not stop within",
        ):
            asyncio.run(_run())
