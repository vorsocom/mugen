"""Application entry point."""

__author__ = "Vorso Computing, Inc."

__copyright__ = "Copyright © 2025, Vorso Computing, Inc."

__email__ = "brightideas@vorsocomputing.com"

__version__ = "0.43.2"

import asyncio
import logging
from time import perf_counter
from types import SimpleNamespace

from mugen import (
    BootstrapError,
    bootstrap_app,
    create_quart_app,
    run_platform_clients,
)
from mugen.bootstrap_state import (
    BOOTSTRAP_STATE_KEY,
    MUGEN_EXTENSION_KEY,
    PHASE_A_STATUS_KEY,
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
    PHASE_STATUS_STOPPED,
    SHUTDOWN_REQUESTED_KEY,
)
from mugen.core import di

_PLATFORM_CLIENTS_TASK_KEY = "platform_clients_task"
_PHASE_B_READINESS_GRACE_KEY = "phase_b_readiness_grace_seconds"
_PHASE_B_CRITICAL_PLATFORMS_KEY = "phase_b_critical_platforms"
_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY = "phase_b_degrade_on_critical_exit"

try:
    # Create Quart mugen.
    app = create_quart_app()
except BootstrapError:
    logging.getLogger(__name__).exception(
        "Application bootstrap failed during app creation."
    )
    raise


def _bootstrap_state() -> dict:
    mugen_state = app.extensions.setdefault(MUGEN_EXTENSION_KEY, {})
    return mugen_state.setdefault(BOOTSTRAP_STATE_KEY, {})


def _resolve_phase_b_runtime_controls() -> tuple[float, list[str], bool]:
    config = getattr(di.container, "config", None)
    if config is None:
        return 0.0, [], True

    mugen_cfg = getattr(config, "mugen", SimpleNamespace())
    runtime_cfg = getattr(mugen_cfg, "runtime", SimpleNamespace())
    phase_b_cfg = getattr(runtime_cfg, "phase_b", SimpleNamespace())

    readiness_grace_raw = getattr(phase_b_cfg, "readiness_grace_seconds", 0.0)
    try:
        readiness_grace = float(readiness_grace_raw)
    except (TypeError, ValueError):
        readiness_grace = 0.0
    if readiness_grace < 0:
        readiness_grace = 0.0

    raw_degrade_on_critical_exit = getattr(phase_b_cfg, "degrade_on_critical_exit", True)
    if isinstance(raw_degrade_on_critical_exit, bool):
        degrade_on_critical_exit = raw_degrade_on_critical_exit
    elif isinstance(raw_degrade_on_critical_exit, str):
        normalized = raw_degrade_on_critical_exit.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            degrade_on_critical_exit = True
        elif normalized in {"0", "false", "no", "off"}:
            degrade_on_critical_exit = False
        else:
            degrade_on_critical_exit = True
    else:
        degrade_on_critical_exit = True

    critical_platforms_raw = getattr(phase_b_cfg, "critical_platforms", None)
    if isinstance(critical_platforms_raw, list):
        critical_platforms = [
            str(item).strip().lower()
            for item in critical_platforms_raw
            if str(item).strip() != ""
        ]
        return readiness_grace, critical_platforms, degrade_on_critical_exit

    active_platforms = getattr(mugen_cfg, "platforms", [])
    if isinstance(active_platforms, list):
        return readiness_grace, [
            str(item).strip().lower()
            for item in active_platforms
            if str(item).strip() != ""
        ], degrade_on_critical_exit
    return readiness_grace, [], degrade_on_critical_exit


def _shutdown_container() -> None:
    try:
        di.shutdown_container()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        app.logger.warning("Container shutdown failed (%s).", exc)


def _on_platform_clients_done(task: asyncio.Task, started_at: float) -> None:
    elapsed_seconds = perf_counter() - started_at
    state = _bootstrap_state()
    shutdown_requested = bool(state.get(SHUTDOWN_REQUESTED_KEY))
    try:
        error = task.exception()
    except asyncio.CancelledError:
        if shutdown_requested:
            state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
            state[PHASE_B_ERROR_KEY] = None
        else:
            state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
            state[PHASE_B_ERROR_KEY] = "phase_b task cancelled unexpectedly"
        app.logger.info(
            "Bootstrap phase_b cancelled elapsed_seconds=%.3f",
            elapsed_seconds,
        )
        return

    if error is None:
        if shutdown_requested:
            state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
            state[PHASE_B_ERROR_KEY] = None
        else:
            platform_statuses = state.get(PHASE_B_PLATFORM_STATUSES_KEY)
            if not isinstance(platform_statuses, dict):
                platform_statuses = {}
            platform_errors = state.get(PHASE_B_PLATFORM_ERRORS_KEY)
            if not isinstance(platform_errors, dict):
                platform_errors = {}
            critical_platforms = state.get(_PHASE_B_CRITICAL_PLATFORMS_KEY, [])
            if not isinstance(critical_platforms, list):
                critical_platforms = []
            degrade_on_critical_exit = state.get(_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY, True)
            if isinstance(degrade_on_critical_exit, str):
                normalized = degrade_on_critical_exit.strip().lower()
                if normalized in {"1", "true", "yes", "on"}:
                    degrade_on_critical_exit = True
                elif normalized in {"0", "false", "no", "off"}:
                    degrade_on_critical_exit = False
                else:
                    degrade_on_critical_exit = True
            elif not isinstance(degrade_on_critical_exit, bool):
                degrade_on_critical_exit = True
            failed_critical: list[str] = []
            for platform in critical_platforms:
                platform_status = str(
                    platform_statuses.get(platform, "")
                ).strip().lower()
                if platform_status == PHASE_STATUS_HEALTHY:
                    continue
                if (
                    platform_status == PHASE_STATUS_STOPPED
                    and degrade_on_critical_exit is not True
                ):
                    continue
                failed_critical.append(platform)
            if failed_critical:
                failed = str(failed_critical[0])
                state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
                state[PHASE_B_ERROR_KEY] = (
                    str(platform_errors.get(failed))
                    or f"critical platform stopped: {failed}"
                )
        app.logger.info(
            "Bootstrap phase_b completed elapsed_seconds=%.3f status=%s",
            elapsed_seconds,
            state.get(PHASE_B_STATUS_KEY),
        )
        return

    state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
    state[PHASE_B_ERROR_KEY] = f"{type(error).__name__}: {error}"
    app.logger.error(
        "Bootstrap phase_b failed elapsed_seconds=%.3f error_type=%s error=%s",
        elapsed_seconds,
        type(error).__name__,
        error,
        exc_info=(type(error), error, error.__traceback__),
    )


@app.before_serving
async def startup():
    """Run app bootstrap before serving and then start platform clients."""
    phase_a_started_at = perf_counter()
    state = _bootstrap_state()
    state[PHASE_A_STATUS_KEY] = PHASE_STATUS_STARTING
    state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
    state[PHASE_B_ERROR_KEY] = None
    state[PHASE_B_PLATFORM_STATUSES_KEY] = {}
    state[PHASE_B_PLATFORM_ERRORS_KEY] = {}
    state[SHUTDOWN_REQUESTED_KEY] = False
    app.logger.info("Bootstrap phase_a starting.")
    try:
        await bootstrap_app(app)
    except BootstrapError:
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_DEGRADED
        app.logger.exception(
            "Bootstrap phase_a failed elapsed_seconds=%.3f",
            perf_counter() - phase_a_started_at,
        )
        raise
    state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
    app.logger.info(
        "Bootstrap phase_a completed elapsed_seconds=%.3f",
        perf_counter() - phase_a_started_at,
    )

    existing_task = state.get(_PLATFORM_CLIENTS_TASK_KEY)
    if isinstance(existing_task, asyncio.Task) and not existing_task.done():
        app.logger.warning("Platform client runner task is already active.")
        return

    readiness_grace_seconds, critical_platforms, degrade_on_critical_exit = (
        _resolve_phase_b_runtime_controls()
    )
    state[_PHASE_B_READINESS_GRACE_KEY] = readiness_grace_seconds
    state[_PHASE_B_CRITICAL_PLATFORMS_KEY] = critical_platforms
    state[_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = degrade_on_critical_exit
    state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
    state[PHASE_B_STARTED_AT_KEY] = perf_counter()
    state[PHASE_B_ERROR_KEY] = None
    phase_b_started_at = perf_counter()
    app.logger.info("Bootstrap phase_b starting.")
    loop = asyncio.get_running_loop()
    task = loop.create_task(
        run_platform_clients(app),
        name="mugen.platform_clients",
    )
    task.add_done_callback(
        lambda done_task: _on_platform_clients_done(done_task, phase_b_started_at)
    )
    state[_PLATFORM_CLIENTS_TASK_KEY] = task


@app.after_serving
async def shutdown():
    """Cancel and await platform client background task during shutdown."""
    state = _bootstrap_state()
    task = state.get(_PLATFORM_CLIENTS_TASK_KEY)
    state[SHUTDOWN_REQUESTED_KEY] = True
    state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
    state[PHASE_B_ERROR_KEY] = None
    if not isinstance(task, asyncio.Task):
        _shutdown_container()
        return

    if task.done():
        state.pop(_PLATFORM_CLIENTS_TASK_KEY, None)
        _shutdown_container()
        return

    app.logger.debug("Cancelling platform client runner task.")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        app.logger.debug("Platform client runner task cancelled during shutdown.")
    finally:
        state.pop(_PLATFORM_CLIENTS_TASK_KEY, None)
        _shutdown_container()
