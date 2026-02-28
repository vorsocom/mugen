"""Phase-B startup plan coordinator shared by runtime adapters."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from mugen.bootstrap_state import (
    PHASE_B_ERROR_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_STARTING,
)
from mugen.core.runtime.phase_b_controls import (
    resolve_phase_b_runtime_controls,
    resolve_phase_b_startup_timeout_seconds,
)

PHASE_B_READINESS_GRACE_KEY = "phase_b_readiness_grace_seconds"
PHASE_B_CRITICAL_PLATFORMS_KEY = "phase_b_critical_platforms"
PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY = "phase_b_degrade_on_critical_exit"
PHASE_B_STARTUP_TIMEOUT_KEY = "phase_b_startup_timeout_seconds"
PHASE_B_STARTUP_PLAN_KEY = "_phase_b_startup_plan"


class _PhaseBRuntimeConfigValidator(Protocol):
    def __call__(
        self,
        *,
        config,
        bootstrap_state: dict,
        logger,
    ) -> tuple[list[str], list[str], bool]: ...


class _WebRuntimeConfigValidator(Protocol):
    def __call__(
        self,
        *,
        config,
        active_platforms: list[str],
    ) -> None: ...


@dataclass(frozen=True)
class PhaseBStartupPlan:
    """Resolved runtime startup controls and validated platform selection."""

    active_platforms: list[str]
    critical_platforms: list[str]
    degrade_on_critical_exit: bool
    readiness_grace_seconds: float
    startup_timeout_seconds: float | None


def build_phase_b_startup_plan(
    *,
    config,
    bootstrap_state: dict,
    logger,
    validate_phase_b_runtime_config: _PhaseBRuntimeConfigValidator,
    validate_web_relational_runtime_config: _WebRuntimeConfigValidator,
    include_startup_timeout: bool,
) -> PhaseBStartupPlan:
    """Build validated phase-B startup controls from runtime config."""
    readiness_grace_seconds, _critical_from_controls, _degrade_from_controls = (
        resolve_phase_b_runtime_controls(config)
    )

    startup_timeout_seconds: float | None = None
    if include_startup_timeout:
        startup_timeout_seconds = resolve_phase_b_startup_timeout_seconds(config)

    active_platforms, critical_platforms, degrade_on_critical_exit = (
        validate_phase_b_runtime_config(
            config=config,
            bootstrap_state=bootstrap_state,
            logger=logger,
        )
    )
    validate_web_relational_runtime_config(
        config=config,
        active_platforms=active_platforms,
    )

    return PhaseBStartupPlan(
        active_platforms=list(active_platforms),
        critical_platforms=list(critical_platforms),
        degrade_on_critical_exit=bool(degrade_on_critical_exit),
        readiness_grace_seconds=float(readiness_grace_seconds),
        startup_timeout_seconds=startup_timeout_seconds,
    )


def apply_phase_b_startup_state(
    bootstrap_state: dict,
    *,
    plan: PhaseBStartupPlan,
    reset_started_at: bool,
) -> None:
    """Persist resolved phase-B startup controls into bootstrap state."""
    bootstrap_state[PHASE_B_READINESS_GRACE_KEY] = plan.readiness_grace_seconds
    bootstrap_state[PHASE_B_CRITICAL_PLATFORMS_KEY] = list(plan.critical_platforms)
    bootstrap_state[PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY] = (
        plan.degrade_on_critical_exit
    )
    if plan.startup_timeout_seconds is not None:
        bootstrap_state[PHASE_B_STARTUP_TIMEOUT_KEY] = plan.startup_timeout_seconds

    bootstrap_state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
    bootstrap_state[PHASE_B_ERROR_KEY] = None
    if reset_started_at:
        bootstrap_state[PHASE_B_STARTED_AT_KEY] = perf_counter()
