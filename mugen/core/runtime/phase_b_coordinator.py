"""Shared phase-B startup-plan coordination for runtime adapters."""

from __future__ import annotations

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
        raise RuntimeError("Invalid runtime configuration: startup timeout is required.")
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
