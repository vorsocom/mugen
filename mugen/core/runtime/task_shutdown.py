"""Shared helpers for bounded task cancellation during shutdown paths."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from math import isfinite
from typing import Iterable


@dataclass(frozen=True)
class TaskCancellationOutcome:
    """Result of bounded cancellation for a collection of tasks."""

    completed_tasks: tuple[asyncio.Task, ...]
    timed_out_tasks: tuple[asyncio.Task, ...]


class TaskCancellationTimeoutError(RuntimeError):
    """Raised when bounded task cancellation leaves unresolved tasks."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        timed_out_tasks: tuple[asyncio.Task, ...],
        message: str,
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = float(timeout_seconds)
        self.timed_out_tasks = timed_out_tasks
        self.timed_out_task_names = tuple(_task_name(task) for task in timed_out_tasks)


def _validate_timeout_seconds(timeout_seconds: float) -> float:
    try:
        parsed = float(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("timeout_seconds must be a positive finite number.") from exc
    if isfinite(parsed) is not True:
        raise RuntimeError("timeout_seconds must be a positive finite number.")
    if parsed <= 0:
        raise RuntimeError("timeout_seconds must be greater than 0.")
    return parsed


def _task_name(task: asyncio.Task) -> str:
    try:
        task_name = task.get_name()
    except Exception:  # pylint: disable=broad-exception-caught
        task_name = None
    if isinstance(task_name, str) and task_name.strip() != "":
        return task_name.strip()
    return repr(task)


async def cancel_tasks_with_timeout(
    tasks: Iterable[asyncio.Task],
    *,
    timeout_seconds: float,
    raise_on_timeout: bool = False,
    timeout_error_prefix: str = "Task cancellation timed out",
) -> TaskCancellationOutcome:
    """Cancel tasks and await completion within a bounded timeout."""
    timeout = _validate_timeout_seconds(timeout_seconds)
    normalized_tasks = tuple(task for task in tasks if isinstance(task, asyncio.Task))
    if not normalized_tasks:
        return TaskCancellationOutcome(completed_tasks=(), timed_out_tasks=())

    completed: set[asyncio.Task] = {task for task in normalized_tasks if task.done()}
    pending = [task for task in normalized_tasks if task.done() is not True]
    for task in pending:
        task.cancel()

    if not pending:
        return TaskCancellationOutcome(
            completed_tasks=tuple(completed),
            timed_out_tasks=(),
        )

    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        completed.update(task for task in pending if task.done())
        timed_out = tuple(task for task in pending if task.done() is not True)
        outcome = TaskCancellationOutcome(
            completed_tasks=tuple(completed),
            timed_out_tasks=timed_out,
        )
        if raise_on_timeout and timed_out:
            timed_out_names = ", ".join(_task_name(task) for task in timed_out)
            raise TaskCancellationTimeoutError(
                timeout_seconds=timeout,
                timed_out_tasks=timed_out,
                message=(
                    f"{timeout_error_prefix} after {timeout:.2f}s "
                    f"(timed_out_tasks={timed_out_names})."
                ),
            )
        return outcome

    completed.update(pending)
    return TaskCancellationOutcome(
        completed_tasks=tuple(completed),
        timed_out_tasks=(),
    )
