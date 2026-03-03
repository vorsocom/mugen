"""Unit tests for phase-B runtime orchestration helpers."""

import asyncio
import unittest
from unittest.mock import patch

from mugen.bootstrap_state import (
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
    PHASE_STATUS_STOPPED,
    SHUTDOWN_REQUESTED_KEY,
)
from mugen.core.runtime import phase_b_runtime as runtime


class TestMugenRuntimePhaseBRuntime(unittest.IsolatedAsyncioTestCase):
    """Covers branch-heavy startup/health orchestration helpers."""

    def test_status_maps_defaults_when_state_is_not_dict(self) -> None:
        statuses, errors = runtime._status_maps(  # pylint: disable=protected-access
            {
                PHASE_B_PLATFORM_STATUSES_KEY: "invalid",
                PHASE_B_PLATFORM_ERRORS_KEY: "invalid",
            }
        )
        self.assertEqual(statuses, {})
        self.assertEqual(errors, {})

    def test_refresh_phase_b_health_updates_aggregate_state(self) -> None:
        state = {
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_HEALTHY},
            PHASE_B_PLATFORM_ERRORS_KEY: {"web": None},
            PHASE_B_STATUS_KEY: PHASE_STATUS_STARTING,
            PHASE_B_ERROR_KEY: None,
            SHUTDOWN_REQUESTED_KEY: False,
        }
        runtime.refresh_phase_b_health(
            state,
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

    async def test_finalize_phase_b_task_completion_cancelled_paths(self) -> None:
        cancelled = asyncio.create_task(asyncio.sleep(1))
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)

        state = {SHUTDOWN_REQUESTED_KEY: True}
        runtime.finalize_phase_b_task_completion(
            state,
            task=cancelled,
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STOPPED)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

        state = {SHUTDOWN_REQUESTED_KEY: False}
        runtime.finalize_phase_b_task_completion(
            state,
            task=cancelled,
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertEqual(state[PHASE_B_ERROR_KEY], "phase_b task cancelled unexpectedly")

    async def test_finalize_phase_b_task_completion_success_and_error_paths(self) -> None:
        async def _ok() -> None:
            return None

        async def _boom() -> None:
            raise ValueError("boom")

        ok_task = asyncio.create_task(_ok())
        await ok_task
        state = {
            SHUTDOWN_REQUESTED_KEY: True,
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_HEALTHY},
            PHASE_B_PLATFORM_ERRORS_KEY: {"web": None},
        }
        runtime.finalize_phase_b_task_completion(
            state,
            task=ok_task,
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STOPPED)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

        state = {
            SHUTDOWN_REQUESTED_KEY: False,
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_HEALTHY},
            PHASE_B_PLATFORM_ERRORS_KEY: {"web": None},
            PHASE_B_STATUS_KEY: PHASE_STATUS_STARTING,
            PHASE_B_ERROR_KEY: None,
        }
        runtime.finalize_phase_b_task_completion(
            state,
            task=ok_task,
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_HEALTHY)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

        boom_task = asyncio.create_task(_boom())
        await asyncio.gather(boom_task, return_exceptions=True)
        runtime.finalize_phase_b_task_completion(
            state,
            task=boom_task,
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
        )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertEqual(state[PHASE_B_ERROR_KEY], "ValueError: boom")

    def test_critical_startup_check_branch_paths(self) -> None:
        check = runtime._critical_startup_check  # pylint: disable=protected-access
        self.assertEqual(
            check(critical_platforms=[], statuses={}, errors={}),
            (True, None),
        )
        self.assertEqual(
            check(
                critical_platforms=["web"],
                statuses={"web": PHASE_STATUS_HEALTHY},
                errors={"web": None},
            ),
            (True, None),
        )
        self.assertEqual(
            check(
                critical_platforms=["web"],
                statuses={"web": PHASE_STATUS_DEGRADED},
                errors={"web": " boom "},
            ),
            (False, "web: boom"),
        )
        self.assertEqual(
            check(
                critical_platforms=["web"],
                statuses={"web": PHASE_STATUS_STOPPED},
                errors={"web": None},
            ),
            (False, "web: status=stopped"),
        )
        self.assertEqual(
            check(
                critical_platforms=["web"],
                statuses={"web": PHASE_STATUS_STARTING},
                errors={"web": None},
            ),
            (False, None),
        )

    async def test_wait_for_critical_startup_branch_paths(self) -> None:
        with self.assertRaises(RuntimeError):
            await runtime.wait_for_critical_startup(
                {},
                critical_platforms=["web"],
                startup_timeout_seconds="bad",  # type: ignore[arg-type]
            )

        with self.assertRaises(RuntimeError):
            await runtime.wait_for_critical_startup(
                {},
                critical_platforms=["web"],
                startup_timeout_seconds=float("inf"),
            )

        with self.assertRaises(RuntimeError):
            await runtime.wait_for_critical_startup(
                {},
                critical_platforms=["web"],
                startup_timeout_seconds=0.0,
            )

        await runtime.wait_for_critical_startup(
            {},
            critical_platforms=[],
            startup_timeout_seconds=1.0,
        )

        with self.assertRaises(RuntimeError):
            await runtime.wait_for_critical_startup(
                {
                    PHASE_B_STATUS_KEY: PHASE_STATUS_DEGRADED,
                    PHASE_B_ERROR_KEY: "boom",
                },
                critical_platforms=["web"],
                startup_timeout_seconds=1.0,
            )

        with self.assertRaises(RuntimeError):
            await runtime.wait_for_critical_startup(
                {
                    PHASE_B_STATUS_KEY: PHASE_STATUS_DEGRADED,
                    PHASE_B_ERROR_KEY: object(),
                },
                critical_platforms=["web"],
                startup_timeout_seconds=1.0,
            )

        await runtime.wait_for_critical_startup(
            {
                PHASE_B_STATUS_KEY: PHASE_STATUS_STARTING,
                PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_HEALTHY},
                PHASE_B_PLATFORM_ERRORS_KEY: {"web": None},
            },
            critical_platforms=["web"],
            startup_timeout_seconds=1.0,
        )

        with self.assertRaises(RuntimeError):
            await runtime.wait_for_critical_startup(
                {
                    PHASE_B_STATUS_KEY: PHASE_STATUS_STARTING,
                    PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_DEGRADED},
                    PHASE_B_PLATFORM_ERRORS_KEY: {"web": "failure"},
                },
                critical_platforms=["web"],
                startup_timeout_seconds=1.0,
            )

        with (
            patch("mugen.core.runtime.phase_b_runtime.perf_counter", side_effect=[0.0, 0.02]),
            self.assertRaises(RuntimeError),
        ):
            await runtime.wait_for_critical_startup(
                {
                    PHASE_B_STATUS_KEY: PHASE_STATUS_STARTING,
                    PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_STARTING},
                    PHASE_B_PLATFORM_ERRORS_KEY: {"web": None},
                },
                critical_platforms=["web"],
                startup_timeout_seconds=0.01,
                poll_interval_seconds=0.0,
            )
