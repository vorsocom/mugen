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
from mugen.core.runtime.phase_b_controls import (
    parse_bool,
    resolve_phase_b_startup_timeout_seconds,
    resolve_phase_b_runtime_controls,
)
from mugen.core.runtime.phase_b_runtime import (
    finalize_phase_b_task_completion,
    wait_for_critical_startup,
)

_PLATFORM_CLIENTS_TASK_KEY = "platform_clients_task"
_PHASE_B_READINESS_GRACE_KEY = "phase_b_readiness_grace_seconds"
_PHASE_B_CRITICAL_PLATFORMS_KEY = "phase_b_critical_platforms"
_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY = "phase_b_degrade_on_critical_exit"
_PHASE_B_STARTUP_TIMEOUT_KEY = "phase_b_startup_timeout_seconds"

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


def _resolve_phase_b_runtime_controls() -> tuple[float, list[str], bool]:
    return resolve_phase_b_runtime_controls(getattr(di.container, "config", None))


def _resolve_phase_b_startup_timeout() -> float:
    return resolve_phase_b_startup_timeout_seconds(getattr(di.container, "config", None))


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
    try:
        startup_timeout_seconds = _resolve_phase_b_startup_timeout()
    except RuntimeError as exc:
        raise BootstrapConfigError(str(exc)) from exc
    runtime_config = getattr(di.container, "config", None)
    if runtime_config is not None:
        active_platforms, critical_platforms, degrade_on_critical_exit = (
            validate_phase_b_runtime_config(
                config=runtime_config,
                bootstrap_state=state,
                logger=app.logger,
            )
        )
        validate_web_relational_runtime_config(
            config=runtime_config,
            active_platforms=active_platforms,
        )
    state[_PHASE_B_READINESS_GRACE_KEY] = readiness_grace_seconds
    state[_PHASE_B_CRITICAL_PLATFORMS_KEY] = critical_platforms
    state[_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = degrade_on_critical_exit
    state[_PHASE_B_STARTUP_TIMEOUT_KEY] = startup_timeout_seconds
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
    try:
        await wait_for_critical_startup(
            state,
            critical_platforms=critical_platforms,
            startup_timeout_seconds=startup_timeout_seconds,
        )
    except RuntimeError as exc:
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
        state[PHASE_B_ERROR_KEY] = str(exc)
        app.logger.error(
            "Bootstrap phase_b startup check failed timeout_seconds=%.3f error=%s",
            startup_timeout_seconds,
            exc,
        )
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        state.pop(_PLATFORM_CLIENTS_TASK_KEY, None)
        raise BootstrapConfigError(str(exc)) from exc


@app.after_serving
async def shutdown():
    """Cancel and await platform client background task during shutdown."""
    state = _bootstrap_state()
    task = state.get(_PLATFORM_CLIENTS_TASK_KEY)
    state[SHUTDOWN_REQUESTED_KEY] = True
    state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STOPPED
    state[PHASE_B_ERROR_KEY] = None
    if not isinstance(task, asyncio.Task):
        await _shutdown_container()
        return

    if task.done():
        state.pop(_PLATFORM_CLIENTS_TASK_KEY, None)
        await _shutdown_container()
        return

    app.logger.debug("Cancelling platform client runner task.")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        app.logger.debug("Platform client runner task cancelled during shutdown.")
    finally:
        state.pop(_PLATFORM_CLIENTS_TASK_KEY, None)
        await _shutdown_container()
