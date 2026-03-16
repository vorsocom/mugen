"""Phase-B shutdown orchestration helpers."""

from __future__ import annotations

import asyncio

from mugen.bootstrap_state import (
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_PLATFORM_TASKS_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_STOPPED,
)
from mugen.core.runtime.task_shutdown import (
    TaskCancellationOutcome,
    TaskCancellationTimeoutError,
    cancel_tasks_with_timeout,
)


class PhaseBShutdownError(RuntimeError):
    """Raised when phase-B shutdown cannot complete deterministically."""


def register_phase_b_platform_task(
    bootstrap_state: dict,
    *,
    platform_name: str,
    task: asyncio.Task,
) -> None:
    """Track one phase-B platform task in bootstrap state."""
    tasks = _phase_b_platform_tasks(bootstrap_state)
    tasks[platform_name] = task
    bootstrap_state[PHASE_B_PLATFORM_TASKS_KEY] = tasks


def unregister_phase_b_platform_task(
    bootstrap_state: dict,
    *,
    platform_name: str,
) -> None:
    """Remove one tracked phase-B platform task from bootstrap state."""
    tasks = _phase_b_platform_tasks(bootstrap_state)
    tasks.pop(platform_name, None)
    bootstrap_state[PHASE_B_PLATFORM_TASKS_KEY] = tasks


def phase_b_platform_tasks(bootstrap_state: dict) -> dict[str, asyncio.Task]:
    """Return a copy of tracked phase-B platform tasks."""
    return dict(_phase_b_platform_tasks(bootstrap_state))


def clear_phase_b_platform_tasks(bootstrap_state: dict) -> None:
    """Clear tracked phase-B platform tasks."""
    bootstrap_state[PHASE_B_PLATFORM_TASKS_KEY] = {}


async def cancel_registered_platform_tasks(
    bootstrap_state: dict,
    *,
    timeout_seconds: float,
    logger,
) -> TaskCancellationOutcome:
    """Cancel tracked phase-B platform tasks with strict timeout behavior."""
    tracked = phase_b_platform_tasks(bootstrap_state)
    active = {
        platform_name: task
        for platform_name, task in tracked.items()
        if isinstance(task, asyncio.Task) and task.done() is not True
    }
    if not active:
        clear_phase_b_platform_tasks(bootstrap_state)
        return TaskCancellationOutcome(completed_tasks=(), timed_out_tasks=())

    try:
        outcome = await cancel_tasks_with_timeout(
            tuple(active.values()),
            timeout_seconds=timeout_seconds,
            raise_on_timeout=True,
            timeout_error_prefix="phase_b platform shutdown timed out",
        )
    except TaskCancellationTimeoutError as exc:
        timed_out_platforms = _timed_out_platform_names(
            active_tasks=active,
            timed_out_tasks=exc.timed_out_tasks,
        )
        if not timed_out_platforms:
            timed_out_platforms = ["<unknown>"]
        timeout_error = f"shutdown timed out after {timeout_seconds:.2f}s"
        for platform_name in timed_out_platforms:
            _set_platform_degraded(
                bootstrap_state,
                platform_name=platform_name,
                error=timeout_error,
            )
        _set_phase_b_degraded(
            bootstrap_state,
            error=(
                "phase_b platform shutdown timed out after "
                f"{timeout_seconds:.2f}s ({', '.join(timed_out_platforms)})"
            ),
        )
        remaining = {
            platform_name: task
            for platform_name, task in active.items()
            if task in exc.timed_out_tasks and task.done() is not True
        }
        bootstrap_state[PHASE_B_PLATFORM_TASKS_KEY] = remaining
        logger.error(
            "Phase-B platform task shutdown timed out timeout_seconds=%.2f platforms=%s",
            timeout_seconds,
            ", ".join(timed_out_platforms),
        )
        raise PhaseBShutdownError(str(exc)) from exc

    clear_phase_b_platform_tasks(bootstrap_state)
    return outcome


async def shutdown_phase_b_runner_task(
    bootstrap_state: dict,
    *,
    task: asyncio.Task,
    timeout_seconds: float,
    logger,
) -> None:
    """Cancel and await phase-B runner task with strict timeout handling."""
    if task.done() is not True:
        try:
            await cancel_tasks_with_timeout(
                (task,),
                timeout_seconds=timeout_seconds,
                raise_on_timeout=True,
                timeout_error_prefix="phase_b shutdown timed out",
            )
        except TaskCancellationTimeoutError as exc:
            _set_phase_b_degraded(
                bootstrap_state,
                error=f"phase_b shutdown timed out after {timeout_seconds:.2f}s",
            )
            logger.error(
                "Platform client runner task did not stop during shutdown "
                "timeout_seconds=%.2f",
                timeout_seconds,
            )
            raise PhaseBShutdownError(str(exc)) from exc

    try:
        await asyncio.gather(task, return_exceptions=False)
    except asyncio.CancelledError:
        logger.debug("Platform client runner task cancelled during shutdown.")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        _set_phase_b_degraded(
            bootstrap_state,
            error=f"{type(exc).__name__}: {exc}",
        )
        logger.error(
            "Platform client runner task raised during shutdown "
            "(error_type=%s error=%s).",
            type(exc).__name__,
            exc,
        )
        raise PhaseBShutdownError(str(exc)) from exc


def reconcile_phase_b_shutdown_state(bootstrap_state: dict) -> None:
    """Finalize phase-B shutdown state without masking degraded signals."""
    status = str(bootstrap_state.get(PHASE_B_STATUS_KEY, "") or "").strip().lower()
    error = bootstrap_state.get(PHASE_B_ERROR_KEY)
    if status == PHASE_STATUS_DEGRADED:
        return
    if isinstance(error, str) and error.strip() != "":
        bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
        return
    unresolved_tasks = _phase_b_platform_tasks(bootstrap_state)
    if unresolved_tasks:
        task_names = ", ".join(sorted(unresolved_tasks.keys()))
        _set_phase_b_degraded(
            bootstrap_state,
            error=f"phase_b platform shutdown unresolved tasks: {task_names}",
        )
        return

    statuses = bootstrap_state.get(PHASE_B_PLATFORM_STATUSES_KEY, {})
    errors = bootstrap_state.get(PHASE_B_PLATFORM_ERRORS_KEY, {})
    if isinstance(statuses, dict):
        for platform_name, platform_status in statuses.items():
            if str(platform_status or "").strip().lower() != PHASE_STATUS_DEGRADED:
                continue
            bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
            platform_error = None
            if isinstance(errors, dict):
                platform_error = errors.get(platform_name)
            if isinstance(platform_error, str) and platform_error.strip() != "":
                bootstrap_state[PHASE_B_ERROR_KEY] = (
                    f"{platform_name}: {platform_error.strip()}"
                )
            return

    bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
    bootstrap_state[PHASE_B_ERROR_KEY] = None


def _phase_b_platform_tasks(bootstrap_state: dict) -> dict[str, asyncio.Task]:
    tasks = bootstrap_state.get(PHASE_B_PLATFORM_TASKS_KEY)
    if not isinstance(tasks, dict):
        return {}
    normalized: dict[str, asyncio.Task] = {}
    for platform_name, task in tasks.items():
        if not isinstance(platform_name, str):
            continue
        if isinstance(task, asyncio.Task) is not True:
            continue
        normalized[platform_name] = task
    return normalized


def _timed_out_platform_names(
    *,
    active_tasks: dict[str, asyncio.Task],
    timed_out_tasks: tuple[asyncio.Task, ...],
) -> list[str]:
    platforms: list[str] = []
    for platform_name, task in active_tasks.items():
        if task not in timed_out_tasks:
            continue
        platforms.append(platform_name)
    return sorted(platforms)


def _set_platform_degraded(
    bootstrap_state: dict,
    *,
    platform_name: str,
    error: str,
) -> None:
    statuses = bootstrap_state.get(PHASE_B_PLATFORM_STATUSES_KEY)
    if not isinstance(statuses, dict):
        statuses = {}
    statuses[platform_name] = PHASE_STATUS_DEGRADED
    bootstrap_state[PHASE_B_PLATFORM_STATUSES_KEY] = statuses

    errors = bootstrap_state.get(PHASE_B_PLATFORM_ERRORS_KEY)
    if not isinstance(errors, dict):
        errors = {}
    errors[platform_name] = error
    bootstrap_state[PHASE_B_PLATFORM_ERRORS_KEY] = errors


def _set_phase_b_degraded(
    bootstrap_state: dict,
    *,
    error: str,
) -> None:
    bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
    bootstrap_state[PHASE_B_ERROR_KEY] = error
