"""Application entry point."""

__author__ = "Vorso Computing, Inc."

__copyright__ = "Copyright © 2025, Vorso Computing, Inc."

__email__ = "brightideas@vorsocomputing.com"

__version__ = "0.43.2"

import asyncio
import logging
from time import perf_counter

from mugen import (
    BootstrapConfigError,
    BootstrapError,
    bootstrap_app,
    create_quart_app,
    run_platform_clients,
    validate_phase_b_runtime_config,
    validate_web_relational_runtime_config,
)
from mugen.bootstrap_state import (
    BOOTSTRAP_STATE_KEY,
    MUGEN_EXTENSION_KEY,
    PHASE_A_BLOCKING_FAILURES_KEY,
    PHASE_A_CAPABILITY_ERRORS_KEY,
    PHASE_A_CAPABILITY_STATUSES_KEY,
    PHASE_A_ERROR_KEY,
    PHASE_A_NON_BLOCKING_DEGRADATIONS_KEY,
    PHASE_A_STATUS_KEY,
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_PLATFORM_TASKS_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
    PHASE_STATUS_STOPPED,
    SHUTDOWN_REQUESTED_KEY,
)
from mugen.core import di
from mugen.core.runtime.phase_b_bootstrap import (
    PHASE_B_CRITICAL_PLATFORMS_KEY as _PHASE_B_CRITICAL_PLATFORMS_KEY,
    PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY as _PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY,
    PHASE_B_STARTUP_PLAN_KEY as _PHASE_B_STARTUP_PLAN_KEY,
)
from mugen.core.contract.runtime_bootstrap import parse_runtime_bootstrap_settings
from mugen.core.runtime.phase_b_coordinator import start_phase_b_runtime
from mugen.core.runtime.phase_b_controls import (
    parse_bool,
)
from mugen.core.runtime.phase_b_runtime import (
    finalize_phase_b_task_completion,
    wait_for_critical_startup,
)
from mugen.core.runtime.phase_b_shutdown import (
    PhaseBShutdownError,
    cancel_registered_platform_tasks,
    clear_phase_b_platform_tasks,
    reconcile_phase_b_shutdown_state,
    shutdown_phase_b_runner_task,
)

_PLATFORM_CLIENTS_TASK_KEY = "platform_clients_task"

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


def _parse_bool(value: object, default: bool = False) -> bool:
    return parse_bool(value, default=default)


def _resolve_shutdown_timeout_seconds() -> float:
    try:
        runtime_config = getattr(di.container, "config", None)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise BootstrapConfigError("Configuration unavailable.") from exc
    if runtime_config is None:
        raise BootstrapConfigError("Configuration unavailable.")
    settings = parse_runtime_bootstrap_settings(runtime_config)
    return float(settings.shutdown_timeout_seconds)


async def _shutdown_container() -> None:
    try:
        await di.shutdown_container_async()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        app.logger.warning("Container shutdown failed (%s).", exc)


def _on_platform_clients_done(task: asyncio.Task, started_at: float) -> None:
    elapsed_seconds = perf_counter() - started_at
    state = _bootstrap_state()
    critical_platforms = state.get(_PHASE_B_CRITICAL_PLATFORMS_KEY, [])
    if not isinstance(critical_platforms, list):
        critical_platforms = []
    degrade_on_critical_exit = _parse_bool(
        state.get(_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY, True),
        default=True,
    )
    finalize_phase_b_task_completion(
        state,
        task=task,
        critical_platforms=critical_platforms,
        degrade_on_critical_exit=degrade_on_critical_exit,
    )
    try:
        task_error = task.exception()
    except asyncio.CancelledError:
        app.logger.info(
            "Bootstrap phase_b cancelled elapsed_seconds=%.3f",
            elapsed_seconds,
        )
        return

    if task_error is None:
        app.logger.info(
            "Bootstrap phase_b completed elapsed_seconds=%.3f status=%s",
            elapsed_seconds,
            state.get(PHASE_B_STATUS_KEY),
        )
        return

    app.logger.error(
        "Bootstrap phase_b failed elapsed_seconds=%.3f error_type=%s error=%s",
        elapsed_seconds,
        type(task_error).__name__,
        task_error,
        exc_info=(type(task_error), task_error, task_error.__traceback__),
    )


@app.before_serving
async def startup():
    """Run app bootstrap before serving and then start platform clients."""
    phase_a_started_at = perf_counter()
    state = _bootstrap_state()
    state[PHASE_A_STATUS_KEY] = PHASE_STATUS_STARTING
    state[PHASE_A_ERROR_KEY] = None
    state[PHASE_A_CAPABILITY_STATUSES_KEY] = {}
    state[PHASE_A_CAPABILITY_ERRORS_KEY] = {}
    state[PHASE_A_BLOCKING_FAILURES_KEY] = []
    state[PHASE_A_NON_BLOCKING_DEGRADATIONS_KEY] = []
    state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
    state[PHASE_B_ERROR_KEY] = None
    state[PHASE_B_PLATFORM_STATUSES_KEY] = {}
    state[PHASE_B_PLATFORM_ERRORS_KEY] = {}
    state[PHASE_B_PLATFORM_TASKS_KEY] = {}
    state[SHUTDOWN_REQUESTED_KEY] = False
    app.logger.info("Bootstrap phase_a starting.")
    try:
        await bootstrap_app(app)
    except BootstrapError:
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_DEGRADED
        current_error = state.get(PHASE_A_ERROR_KEY)
        if not isinstance(current_error, str) or current_error.strip() == "":
            state[PHASE_A_ERROR_KEY] = "phase_a bootstrap failed"
        app.logger.error(
            "Bootstrap phase_a failed elapsed_seconds=%.3f",
            perf_counter() - phase_a_started_at,
            exc_info=True,
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

    try:
        runtime_config = getattr(di.container, "config", None)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise BootstrapConfigError("Configuration unavailable.") from exc
    if runtime_config is None:
        raise BootstrapConfigError("Configuration unavailable.")

    phase_b_started_at = perf_counter()
    app.logger.info("Bootstrap phase_b starting.")
    try:
        _, task = await start_phase_b_runtime(
            app=app,
            config=runtime_config,
            bootstrap_state=state,
            logger=app.logger,
            run_platform_clients=run_platform_clients,
            wait_for_critical_startup=wait_for_critical_startup,
            validate_phase_b_runtime_config=validate_phase_b_runtime_config,
            validate_web_relational_runtime_config=validate_web_relational_runtime_config,
            task_name="mugen.platform_clients",
        )
        task.add_done_callback(
            lambda done_task: _on_platform_clients_done(done_task, phase_b_started_at)
        )
        state[_PLATFORM_CLIENTS_TASK_KEY] = task
    except RuntimeError as exc:
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
        state[PHASE_B_ERROR_KEY] = str(exc)
        app.logger.error(
            "Bootstrap phase_b startup check failed error=%s",
            exc,
        )
        state.pop(_PLATFORM_CLIENTS_TASK_KEY, None)
        state.pop(_PHASE_B_STARTUP_PLAN_KEY, None)
        raise BootstrapConfigError(str(exc)) from exc


@app.after_serving
async def shutdown():
    """Cancel and await platform client background task during shutdown."""
    state = _bootstrap_state()
    state[SHUTDOWN_REQUESTED_KEY] = True
    task = state.get(_PLATFORM_CLIENTS_TASK_KEY)
    shutdown_timeout_seconds = _resolve_shutdown_timeout_seconds()
    shutdown_error: PhaseBShutdownError | None = None
    if isinstance(task, asyncio.Task):
        app.logger.debug(
            "Cancelling platform client runner task timeout_seconds=%.2f",
            shutdown_timeout_seconds,
        )
    try:
        await cancel_registered_platform_tasks(
            state,
            timeout_seconds=shutdown_timeout_seconds,
            logger=app.logger,
        )
        if isinstance(task, asyncio.Task):
            await shutdown_phase_b_runner_task(
                state,
                task=task,
                timeout_seconds=shutdown_timeout_seconds,
                logger=app.logger,
            )
    except PhaseBShutdownError as exc:
        shutdown_error = exc
        app.logger.error("Bootstrap phase_b shutdown failed error=%s", exc)
    finally:
        if shutdown_error is None:
            clear_phase_b_platform_tasks(state)
        reconcile_phase_b_shutdown_state(state)
        state.pop(_PLATFORM_CLIENTS_TASK_KEY, None)
        try:
            await _shutdown_container()
        finally:
            if isinstance(state.get(PHASE_B_PLATFORM_TASKS_KEY), dict) is not True:
                state[PHASE_B_PLATFORM_TASKS_KEY] = {}
