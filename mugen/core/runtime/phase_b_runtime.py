"""Phase-B runtime startup and health orchestration helpers."""

from __future__ import annotations

import asyncio
from time import perf_counter

from mugen.bootstrap_state import (
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STOPPED,
    SHUTDOWN_REQUESTED_KEY,
)
from mugen.core.domain.use_case.phase_b_health import (
    PhaseBHealthInput,
    evaluate_phase_b_health,
)
from mugen.core.runtime.phase_b_controls import parse_bool


def _status_maps(
    bootstrap_state: dict,
) -> tuple[dict[str, str], dict[str, str | None]]:
    statuses = bootstrap_state.get(PHASE_B_PLATFORM_STATUSES_KEY)
    if not isinstance(statuses, dict):
        statuses = {}
    errors = bootstrap_state.get(PHASE_B_PLATFORM_ERRORS_KEY)
    if not isinstance(errors, dict):
        errors = {}
    return statuses, errors


def refresh_phase_b_health(
    bootstrap_state: dict,
    *,
    critical_platforms: list[str],
    degrade_on_critical_exit: bool,
) -> None:
    """Recompute aggregate phase-B health from per-platform statuses."""
    statuses, errors = _status_maps(bootstrap_state)
    evaluation = evaluate_phase_b_health(
        PhaseBHealthInput(
            platform_statuses=statuses,
            platform_errors=errors,
            critical_platforms=list(critical_platforms),
            degrade_on_critical_exit=degrade_on_critical_exit,
            shutdown_requested=parse_bool(
                bootstrap_state.get(SHUTDOWN_REQUESTED_KEY),
                default=False,
            ),
            phase_b_status=str(bootstrap_state.get(PHASE_B_STATUS_KEY, "") or ""),
            phase_b_error=bootstrap_state.get(PHASE_B_ERROR_KEY),
            phase_b_started_at=bootstrap_state.get(PHASE_B_STARTED_AT_KEY),
            readiness_grace_seconds=0.0,
        )
    )
    bootstrap_state[PHASE_B_STATUS_KEY] = evaluation.phase_b_status
    bootstrap_state[PHASE_B_ERROR_KEY] = evaluation.phase_b_error


def finalize_phase_b_task_completion(
    bootstrap_state: dict,
    *,
    task: asyncio.Task,
    critical_platforms: list[str],
    degrade_on_critical_exit: bool,
) -> None:
    """Apply terminal aggregate status for the phase-B runner task."""
    shutdown_requested = bool(bootstrap_state.get(SHUTDOWN_REQUESTED_KEY))
    try:
        error = task.exception()
    except asyncio.CancelledError:
        if shutdown_requested:
            bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
            bootstrap_state[PHASE_B_ERROR_KEY] = None
            return
        bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
        bootstrap_state[PHASE_B_ERROR_KEY] = "phase_b task cancelled unexpectedly"
        return

    if error is None:
        if shutdown_requested:
            bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
            bootstrap_state[PHASE_B_ERROR_KEY] = None
            return
        refresh_phase_b_health(
            bootstrap_state,
            critical_platforms=critical_platforms,
            degrade_on_critical_exit=degrade_on_critical_exit,
        )
        return

    bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
    bootstrap_state[PHASE_B_ERROR_KEY] = f"{type(error).__name__}: {error}"


def _critical_startup_check(
    *,
    critical_platforms: list[str],
    statuses: dict[str, str],
    errors: dict[str, str | None],
) -> tuple[bool, str | None]:
    if not critical_platforms:
        return True, None

    all_healthy = True
    for platform in critical_platforms:
        status = str(statuses.get(platform, "") or "").strip().lower()
        if status == PHASE_STATUS_HEALTHY:
            continue
        all_healthy = False
        if status in {PHASE_STATUS_DEGRADED, PHASE_STATUS_STOPPED}:
            error = errors.get(platform)
            if isinstance(error, str) and error.strip():
                return False, f"{platform}: {error.strip()}"
            return False, f"{platform}: status={status}"
    if all_healthy:
        return True, None
    return False, None


async def wait_for_critical_startup(
    bootstrap_state: dict,
    *,
    critical_platforms: list[str],
    startup_timeout_seconds: float,
    poll_interval_seconds: float = 0.05,
) -> None:
    """Block startup until all critical platforms report healthy, or fail."""
    if startup_timeout_seconds <= 0:
        raise RuntimeError("startup_timeout_seconds must be greater than 0.")
    if not critical_platforms:
        return

    deadline = perf_counter() + startup_timeout_seconds
    while True:
        phase_b_status = str(bootstrap_state.get(PHASE_B_STATUS_KEY, "") or "").strip().lower()
        phase_b_error = bootstrap_state.get(PHASE_B_ERROR_KEY)
        if phase_b_status == PHASE_STATUS_DEGRADED:
            error_text = (
                phase_b_error.strip()
                if isinstance(phase_b_error, str) and phase_b_error.strip()
                else "phase_b degraded"
            )
            raise RuntimeError(
                "Critical platform startup failed: "
                f"{error_text}."
            )

        statuses, errors = _status_maps(bootstrap_state)
        all_healthy, failure_reason = _critical_startup_check(
            critical_platforms=critical_platforms,
            statuses=statuses,
            errors=errors,
        )
        if all_healthy:
            return
        if failure_reason is not None:
            raise RuntimeError(
                "Critical platform startup failed: "
                f"{failure_reason}."
            )

        if perf_counter() >= deadline:
            pending = [
                platform
                for platform in critical_platforms
                if str(statuses.get(platform, "") or "").strip().lower()
                != PHASE_STATUS_HEALTHY
            ]
            pending_text = ", ".join(pending) if pending else "<none>"
            raise RuntimeError(
                "Critical platform startup timed out. "
                f"Pending platforms: {pending_text}."
            )

        await asyncio.sleep(poll_interval_seconds)
