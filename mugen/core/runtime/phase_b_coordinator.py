"""Shared phase-B startup-plan coordination for runtime adapters."""

from __future__ import annotations

import asyncio

from mugen.core.runtime.phase_b_controls import (
    resolve_phase_b_startup_failure_cancel_timeout_seconds,
)
from mugen.core.runtime.phase_b_bootstrap import (
    PHASE_B_STARTUP_PLAN_KEY,
    PhaseBStartupPlan,
    apply_phase_b_startup_state,
    build_phase_b_startup_plan,
)


def _build_startup_plan(
    *,
    config,
    bootstrap_state: dict,
    logger,
    validate_phase_b_runtime_config,
    validate_web_relational_runtime_config,
) -> PhaseBStartupPlan:
    plan = build_phase_b_startup_plan(
        config=config,
        bootstrap_state=bootstrap_state,
        logger=logger,
        validate_phase_b_runtime_config=validate_phase_b_runtime_config,
        validate_web_relational_runtime_config=validate_web_relational_runtime_config,
        include_startup_timeout=True,
    )
    if plan.startup_timeout_seconds is None:
        raise RuntimeError(
            "Invalid runtime configuration: startup timeout is required."
        )
    return plan


def prepare_phase_b_startup_plan(
    *,
    config,
    bootstrap_state: dict,
    logger,
    validate_phase_b_runtime_config,
    validate_web_relational_runtime_config,
) -> PhaseBStartupPlan:
    """Build, validate, and store canonical phase-B startup plan."""
    plan = _build_startup_plan(
        config=config,
        bootstrap_state=bootstrap_state,
        logger=logger,
        validate_phase_b_runtime_config=validate_phase_b_runtime_config,
        validate_web_relational_runtime_config=validate_web_relational_runtime_config,
    )
    apply_phase_b_startup_state(
        bootstrap_state,
        plan=plan,
        reset_started_at=True,
    )
    bootstrap_state[PHASE_B_STARTUP_PLAN_KEY] = plan
    return plan


def resolve_phase_b_startup_plan(
    *,
    config,
    bootstrap_state: dict,
    logger,
    validate_phase_b_runtime_config,
    validate_web_relational_runtime_config,
) -> PhaseBStartupPlan:
    """Resolve startup plan from bootstrap state, else build canonical plan."""
    startup_plan = bootstrap_state.pop(PHASE_B_STARTUP_PLAN_KEY, None)
    if isinstance(startup_plan, PhaseBStartupPlan):
        apply_phase_b_startup_state(
            bootstrap_state,
            plan=startup_plan,
            reset_started_at=False,
        )
        return startup_plan

    return prepare_phase_b_startup_plan(
        config=config,
        bootstrap_state=bootstrap_state,
        logger=logger,
        validate_phase_b_runtime_config=validate_phase_b_runtime_config,
        validate_web_relational_runtime_config=validate_web_relational_runtime_config,
    )


async def start_phase_b_runtime(
    *,
    app,
    config,
    bootstrap_state: dict,
    logger,
    run_platform_clients,
    wait_for_critical_startup,
    validate_phase_b_runtime_config,
    validate_web_relational_runtime_config,
    task_name: str = "mugen.platform_clients",
) -> tuple[PhaseBStartupPlan, asyncio.Task]:
    """Start platform runner task with canonical startup gating semantics."""
    plan = prepare_phase_b_startup_plan(
        config=config,
        bootstrap_state=bootstrap_state,
        logger=logger,
        validate_phase_b_runtime_config=validate_phase_b_runtime_config,
        validate_web_relational_runtime_config=validate_web_relational_runtime_config,
    )
    startup_timeout_seconds = plan.startup_timeout_seconds
    if startup_timeout_seconds is None:
        raise RuntimeError(
            "Invalid runtime configuration: startup timeout is required."
        )

    loop = asyncio.get_running_loop()
    task = loop.create_task(
        run_platform_clients(app),
        name=task_name,
    )
    try:
        await wait_for_critical_startup(
            bootstrap_state,
            critical_platforms=plan.critical_platforms,
            startup_timeout_seconds=startup_timeout_seconds,
        )
    except Exception:
        if not task.done():
            task.cancel()
            cancel_timeout_seconds = (
                resolve_phase_b_startup_failure_cancel_timeout_seconds(config)
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(task, return_exceptions=True),
                    timeout=cancel_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    "Phase-B runner did not stop within "
                    f"{cancel_timeout_seconds:.2f}s after critical startup failure; "
                    "check provider cancellation handling or increase "
                    "mugen.runtime.provider_shutdown_timeout_seconds."
                ) from exc
        raise
    return plan, task
