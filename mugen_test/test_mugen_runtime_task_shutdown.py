"""Unit coverage for bounded task shutdown helper branches."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from mugen.core.runtime.task_shutdown import cancel_tasks_with_timeout


class TestMugenRuntimeTaskShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_tasks_with_timeout_rejects_non_numeric_timeout(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "positive number"):
            await cancel_tasks_with_timeout((), timeout_seconds="bad")

    async def test_cancel_tasks_with_timeout_rejects_non_positive_timeout(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "greater than 0"):
            await cancel_tasks_with_timeout((), timeout_seconds=0)

    async def test_cancel_tasks_with_timeout_returns_empty_for_no_tasks(self) -> None:
        outcome = await cancel_tasks_with_timeout((), timeout_seconds=1.0)
        self.assertEqual(outcome.completed_tasks, ())
        self.assertEqual(outcome.timed_out_tasks, ())

    async def test_cancel_tasks_with_timeout_returns_completed_when_only_done_tasks(self) -> None:
        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        outcome = await cancel_tasks_with_timeout((done_task,), timeout_seconds=1.0)
        self.assertIn(done_task, outcome.completed_tasks)
        self.assertEqual(outcome.timed_out_tasks, ())

    async def test_cancel_tasks_with_timeout_returns_timed_out_tasks_on_timeout(self) -> None:
        pending_task = asyncio.create_task(asyncio.sleep(60))

        def _raise_timeout(awaitable, timeout):  # noqa: ARG001
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError

        with patch(
            "mugen.core.runtime.task_shutdown.asyncio.wait_for",
            side_effect=_raise_timeout,
        ):
            outcome = await cancel_tasks_with_timeout((pending_task,), timeout_seconds=0.01)

        self.assertIn(pending_task, outcome.timed_out_tasks)
        pending_task.cancel()
        await asyncio.gather(pending_task, return_exceptions=True)
