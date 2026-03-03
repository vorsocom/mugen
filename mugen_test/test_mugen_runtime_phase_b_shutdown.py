"""Unit tests for phase-B shutdown orchestration helpers."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.bootstrap_state import (
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_PLATFORM_TASKS_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_STOPPED,
)
from mugen.core.runtime import phase_b_shutdown as phase_b_shutdown_mod
from mugen.core.runtime.phase_b_shutdown import (
    PhaseBShutdownError,
    cancel_registered_platform_tasks,
    clear_phase_b_platform_tasks,
    phase_b_platform_tasks,
    reconcile_phase_b_shutdown_state,
    register_phase_b_platform_task,
    shutdown_phase_b_runner_task,
    unregister_phase_b_platform_task,
)
from mugen.core.runtime.task_shutdown import TaskCancellationTimeoutError


class TestMugenRuntimePhaseBShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_task_registry_helpers(self) -> None:
        state: dict = {}
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        register_phase_b_platform_task(state, platform_name="web", task=task)
        self.assertEqual(phase_b_platform_tasks(state), {"web": task})
        unregister_phase_b_platform_task(state, platform_name="web")
        self.assertEqual(phase_b_platform_tasks(state), {})
        clear_phase_b_platform_tasks(state)
        self.assertEqual(state[PHASE_B_PLATFORM_TASKS_KEY], {})

    async def test_cancel_registered_platform_tasks_success_clears_registry(self) -> None:
        state: dict = {}
        blocker = asyncio.Event()
        task = asyncio.create_task(blocker.wait(), name="mugen.platform.web")
        register_phase_b_platform_task(state, platform_name="web", task=task)
        logger = Mock()

        outcome = await cancel_registered_platform_tasks(
            state,
            timeout_seconds=0.01,
            logger=logger,
        )

        self.assertEqual(outcome.timed_out_tasks, ())
        self.assertEqual(state[PHASE_B_PLATFORM_TASKS_KEY], {})
        self.assertTrue(task.done())

    async def test_cancel_registered_platform_tasks_timeout_marks_degraded(self) -> None:
        state: dict = {}
        task = asyncio.create_task(asyncio.sleep(60), name="mugen.platform.matrix")
        register_phase_b_platform_task(state, platform_name="matrix", task=task)
        logger = Mock()

        timeout_error = TaskCancellationTimeoutError(
            timeout_seconds=0.01,
            timed_out_tasks=(task,),
            message=(
                "phase_b platform shutdown timed out after 0.01s "
                "(timed_out_tasks=mugen.platform.matrix)."
            ),
        )
        with (
            patch(
                "mugen.core.runtime.phase_b_shutdown.cancel_tasks_with_timeout",
                new=AsyncMock(side_effect=timeout_error),
            ),
            self.assertRaises(PhaseBShutdownError),
        ):
            await cancel_registered_platform_tasks(
                state,
                timeout_seconds=0.01,
                logger=logger,
            )

        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn("phase_b platform shutdown timed out after 0.01s", state[PHASE_B_ERROR_KEY])
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["matrix"], PHASE_STATUS_DEGRADED)
        self.assertIn("shutdown timed out after 0.01s", state[PHASE_B_PLATFORM_ERRORS_KEY]["matrix"])
        self.assertEqual(state[PHASE_B_PLATFORM_TASKS_KEY], {"matrix": task})
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_cancel_registered_platform_tasks_timeout_without_matching_tasks_uses_unknown(
        self,
    ) -> None:
        state: dict = {}
        task = asyncio.create_task(asyncio.sleep(60), name="mugen.platform.matrix")
        register_phase_b_platform_task(state, platform_name="matrix", task=task)
        other = asyncio.create_task(asyncio.sleep(60), name="mugen.platform.other")
        logger = Mock()
        timeout_error = TaskCancellationTimeoutError(
            timeout_seconds=0.01,
            timed_out_tasks=(other,),
            message=(
                "phase_b platform shutdown timed out after 0.01s "
                "(timed_out_tasks=mugen.platform.other)."
            ),
        )
        with (
            patch(
                "mugen.core.runtime.phase_b_shutdown.cancel_tasks_with_timeout",
                new=AsyncMock(side_effect=timeout_error),
            ),
            self.assertRaises(PhaseBShutdownError),
        ):
            await cancel_registered_platform_tasks(
                state,
                timeout_seconds=0.01,
                logger=logger,
            )

        self.assertEqual(
            state[PHASE_B_PLATFORM_STATUSES_KEY]["<unknown>"],
            PHASE_STATUS_DEGRADED,
        )
        task.cancel()
        other.cancel()
        await asyncio.gather(task, other, return_exceptions=True)

    async def test_shutdown_phase_b_runner_task_timeout_marks_degraded(self) -> None:
        state: dict = {}
        task = asyncio.create_task(asyncio.sleep(60), name="mugen.platform.runner")
        logger = Mock()
        timeout_error = TaskCancellationTimeoutError(
            timeout_seconds=0.01,
            timed_out_tasks=(task,),
            message=(
                "phase_b shutdown timed out after 0.01s "
                "(timed_out_tasks=mugen.platform.runner)."
            ),
        )
        with (
            patch(
                "mugen.core.runtime.phase_b_shutdown.cancel_tasks_with_timeout",
                new=AsyncMock(side_effect=timeout_error),
            ),
            self.assertRaises(PhaseBShutdownError),
        ):
            await shutdown_phase_b_runner_task(
                state,
                task=task,
                timeout_seconds=0.01,
                logger=logger,
            )
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn("phase_b shutdown timed out after 0.01s", state[PHASE_B_ERROR_KEY])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_reconcile_phase_b_shutdown_state_stops_on_clean_shutdown(self) -> None:
        state = {
            PHASE_B_STATUS_KEY: "healthy",
            PHASE_B_ERROR_KEY: None,
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_STOPPED},
            PHASE_B_PLATFORM_ERRORS_KEY: {"web": None},
            PHASE_B_PLATFORM_TASKS_KEY: {},
        }
        reconcile_phase_b_shutdown_state(state)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STOPPED)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

    async def test_reconcile_phase_b_shutdown_state_marks_degraded_when_error_present(
        self,
    ) -> None:
        state = {
            PHASE_B_STATUS_KEY: "healthy",
            PHASE_B_ERROR_KEY: "existing error",
        }
        reconcile_phase_b_shutdown_state(state)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)

    async def test_reconcile_phase_b_shutdown_state_uses_platform_error_for_degraded_platform(
        self,
    ) -> None:
        state = {
            PHASE_B_STATUS_KEY: "healthy",
            PHASE_B_ERROR_KEY: None,
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_DEGRADED},
            PHASE_B_PLATFORM_ERRORS_KEY: {"web": "shutdown timeout"},
            PHASE_B_PLATFORM_TASKS_KEY: {},
        }
        reconcile_phase_b_shutdown_state(state)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertEqual(state[PHASE_B_ERROR_KEY], "web: shutdown timeout")

    async def test_reconcile_phase_b_shutdown_state_handles_non_dict_error_map(
        self,
    ) -> None:
        state = {
            PHASE_B_STATUS_KEY: "healthy",
            PHASE_B_ERROR_KEY: None,
            PHASE_B_PLATFORM_STATUSES_KEY: {"web": PHASE_STATUS_DEGRADED},
            PHASE_B_PLATFORM_ERRORS_KEY: "invalid",
            PHASE_B_PLATFORM_TASKS_KEY: {},
        }
        reconcile_phase_b_shutdown_state(state)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])

    async def test_reconcile_phase_b_shutdown_state_stops_when_status_map_is_not_dict(
        self,
    ) -> None:
        state = {
            PHASE_B_STATUS_KEY: "healthy",
            PHASE_B_ERROR_KEY: None,
            PHASE_B_PLATFORM_STATUSES_KEY: "invalid",
            PHASE_B_PLATFORM_ERRORS_KEY: {},
            PHASE_B_PLATFORM_TASKS_KEY: {},
        }
        reconcile_phase_b_shutdown_state(state)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STOPPED)

    async def test_reconcile_phase_b_shutdown_state_keeps_degraded_when_unresolved_tasks(
        self,
    ) -> None:
        state: dict = {
            PHASE_B_STATUS_KEY: "healthy",
            PHASE_B_ERROR_KEY: None,
            PHASE_B_PLATFORM_STATUSES_KEY: {},
            PHASE_B_PLATFORM_ERRORS_KEY: {},
        }
        unresolved = asyncio.create_task(asyncio.sleep(60))
        state[PHASE_B_PLATFORM_TASKS_KEY] = {"web": unresolved}

        reconcile_phase_b_shutdown_state(state)

        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_DEGRADED)
        self.assertIn("unresolved tasks", state[PHASE_B_ERROR_KEY])
        unresolved.cancel()
        await asyncio.gather(unresolved, return_exceptions=True)

    async def test_private_helpers_normalize_invalid_entries(self) -> None:
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        normalized = phase_b_shutdown_mod._phase_b_platform_tasks(  # pylint: disable=protected-access
            {
                PHASE_B_PLATFORM_TASKS_KEY: {
                    1: task,
                    "web": object(),
                    "matrix": task,
                }
            }
        )
        self.assertEqual(normalized, {"matrix": task})

        skipped = phase_b_shutdown_mod._timed_out_platform_names(  # pylint: disable=protected-access
            active_tasks={"matrix": task},
            timed_out_tasks=(),
        )
        self.assertEqual(skipped, [])

        state = {
            PHASE_B_PLATFORM_STATUSES_KEY: "bad",
            PHASE_B_PLATFORM_ERRORS_KEY: "bad",
        }
        phase_b_shutdown_mod._set_platform_degraded(  # pylint: disable=protected-access
            state,
            platform_name="web",
            error="timeout",
        )
        self.assertEqual(state[PHASE_B_PLATFORM_STATUSES_KEY]["web"], PHASE_STATUS_DEGRADED)
        self.assertEqual(state[PHASE_B_PLATFORM_ERRORS_KEY]["web"], "timeout")

        state_dict_maps = {
            PHASE_B_PLATFORM_STATUSES_KEY: {},
            PHASE_B_PLATFORM_ERRORS_KEY: {},
        }
        phase_b_shutdown_mod._set_platform_degraded(  # pylint: disable=protected-access
            state_dict_maps,
            platform_name="matrix",
            error="timeout",
        )
        self.assertEqual(
            state_dict_maps[PHASE_B_PLATFORM_STATUSES_KEY]["matrix"],
            PHASE_STATUS_DEGRADED,
        )
        self.assertEqual(
            state_dict_maps[PHASE_B_PLATFORM_ERRORS_KEY]["matrix"],
            "timeout",
        )
