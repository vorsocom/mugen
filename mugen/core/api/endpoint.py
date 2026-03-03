"""Implements API endpoints."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from quart import current_app, jsonify

from mugen.bootstrap_state import (
    PHASE_A_BLOCKING_FAILURES_KEY,
    PHASE_A_CAPABILITY_ERRORS_KEY,
    PHASE_A_CAPABILITY_STATUSES_KEY,
    PHASE_A_ERROR_KEY,
    PHASE_A_NON_BLOCKING_DEGRADATIONS_KEY,
    PHASE_A_STATUS_KEY,
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_HEALTHY,
    get_bootstrap_state,
)
from mugen.core.api import api
from mugen.core.domain.use_case.phase_b_health import (
    PHASE_STATUS_DEGRADED,
    PhaseBHealthInput,
    evaluate_phase_b_health,
)
from mugen.core.utility.config_value import (
    parse_bool_flag,
    parse_nonnegative_finite_float,
)
from mugen.core.utility.platforms import normalize_platforms

_PHASE_B_READINESS_GRACE_KEY = "phase_b_readiness_grace_seconds"
_PHASE_B_CRITICAL_PLATFORMS_KEY = "phase_b_critical_platforms"
_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY = "phase_b_degrade_on_critical_exit"


def _resolve_bootstrap_status() -> dict[str, Any]:
    state = get_bootstrap_state(current_app)
    return {
        "phase_a_status": str(state.get(PHASE_A_STATUS_KEY, "") or ""),
        "phase_a_error": state.get(PHASE_A_ERROR_KEY),
        "phase_a_capability_statuses": state.get(PHASE_A_CAPABILITY_STATUSES_KEY, {}),
        "phase_a_capability_errors": state.get(PHASE_A_CAPABILITY_ERRORS_KEY, {}),
        "phase_a_blocking_failures": state.get(PHASE_A_BLOCKING_FAILURES_KEY, []),
        "phase_a_non_blocking_degradations": state.get(
            PHASE_A_NON_BLOCKING_DEGRADATIONS_KEY,
            [],
        ),
        "phase_b_status": str(state.get(PHASE_B_STATUS_KEY, "") or ""),
        "phase_b_error": state.get(PHASE_B_ERROR_KEY),
        "phase_b_started_at": state.get(PHASE_B_STARTED_AT_KEY),
        "phase_b_readiness_grace_seconds": state.get(_PHASE_B_READINESS_GRACE_KEY, 0.0),
        "phase_b_critical_platforms": state.get(_PHASE_B_CRITICAL_PLATFORMS_KEY, []),
        "phase_b_degrade_on_critical_exit": state.get(
            _PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY,
            True,
        ),
        "phase_b_platform_statuses": state.get(PHASE_B_PLATFORM_STATUSES_KEY, {}),
        "phase_b_platform_errors": state.get(PHASE_B_PLATFORM_ERRORS_KEY, {}),
    }


def _normalize_string_list(values: object) -> list[str]:
    if isinstance(values, list) is not True:
        return []
    normalized: list[str] = []
    for value in values:
        if isinstance(value, str) is not True:
            continue
        candidate = value.strip()
        if candidate == "" or candidate in normalized:
            continue
        normalized.append(candidate)
    return normalized


@api.get("/core/health/live")
async def core_health_live():
    """Liveness health probe."""
    status = _resolve_bootstrap_status()
    return (
        jsonify(
            {
                "status": "live",
                "phase_a_status": status["phase_a_status"],
                "phase_a_error": status["phase_a_error"],
                "phase_b_status": status["phase_b_status"],
            }
        ),
        200,
    )


@api.get("/core/health/ready")
async def core_health_ready():
    """Readiness health probe."""
    status = _resolve_bootstrap_status()
    phase_a_status = status["phase_a_status"]
    phase_a_error = status["phase_a_error"]
    raw_phase_a_capability_statuses = status["phase_a_capability_statuses"]
    raw_phase_a_capability_errors = status["phase_a_capability_errors"]
    phase_a_capability_statuses: dict[str, str] = {}
    if isinstance(raw_phase_a_capability_statuses, dict):
        for capability_name, capability_status in raw_phase_a_capability_statuses.items():
            if not isinstance(capability_name, str):
                continue
            normalized_name = capability_name.strip()
            if normalized_name == "":
                continue
            if not isinstance(capability_status, str):
                continue
            normalized_status = capability_status.strip()
            if normalized_status == "":
                continue
            phase_a_capability_statuses[normalized_name] = normalized_status

    phase_a_capability_errors: dict[str, str] = {}
    if isinstance(raw_phase_a_capability_errors, dict):
        for capability_name, capability_error in raw_phase_a_capability_errors.items():
            if not isinstance(capability_name, str):
                continue
            normalized_name = capability_name.strip()
            if normalized_name == "":
                continue
            if not isinstance(capability_error, str):
                continue
            normalized_error = capability_error.strip()
            if normalized_error == "":
                continue
            phase_a_capability_errors[normalized_name] = normalized_error
    phase_a_capability_reasons: dict[str, str] = dict(phase_a_capability_errors)

    phase_a_blocking_failed_capabilities = _normalize_string_list(
        status["phase_a_blocking_failures"]
    )
    phase_a_non_blocking_degraded_capabilities = _normalize_string_list(
        status["phase_a_non_blocking_degradations"]
    )
    if (
        not phase_a_blocking_failed_capabilities
        and phase_a_status != PHASE_STATUS_HEALTHY
    ):
        phase_a_blocking_failed_capabilities = sorted(phase_a_capability_reasons.keys())

    try:
        readiness_grace_seconds = parse_nonnegative_finite_float(
            status["phase_b_readiness_grace_seconds"],
            field_name="phase_b_readiness_grace_seconds",
            default=0.0,
        )
    except RuntimeError:
        # Invalid health-state grace values are treated strictly (no grace).
        readiness_grace_seconds = 0.0
    degrade_on_critical_exit = parse_bool_flag(
        status["phase_b_degrade_on_critical_exit"],
        default=True,
    )
    critical_platforms = normalize_platforms(status["phase_b_critical_platforms"])

    health = evaluate_phase_b_health(
        PhaseBHealthInput(
            platform_statuses=status["phase_b_platform_statuses"],
            platform_errors=status["phase_b_platform_errors"],
            critical_platforms=critical_platforms,
            degrade_on_critical_exit=degrade_on_critical_exit,
            shutdown_requested=False,
            phase_b_status=status["phase_b_status"],
            phase_b_error=status["phase_b_error"],
            phase_b_started_at=status["phase_b_started_at"],
            readiness_grace_seconds=readiness_grace_seconds,
            include_starting_failures=True,
            now_monotonic=perf_counter(),
        )
    )
    phase_b_status = health.phase_b_status
    phase_b_error = health.phase_b_error
    failed_platforms = health.failed_critical_platforms
    reasons: dict[str, str] = dict(health.reasons)

    if phase_a_status != PHASE_STATUS_HEALTHY:
        if isinstance(phase_a_error, str) and phase_a_error.strip():
            reasons["phase_a"] = phase_a_error.strip()
        for capability_name in phase_a_blocking_failed_capabilities:
            capability_error = phase_a_capability_reasons.get(capability_name)
            if capability_error is None:
                continue
            reasons[f"phase_a.{capability_name}"] = capability_error

    phase_a_failed_capabilities = list(phase_a_blocking_failed_capabilities)
    phase_a_blocking_capability_errors: dict[str, str] = {
        capability_name: phase_a_capability_reasons[capability_name]
        for capability_name in phase_a_blocking_failed_capabilities
        if capability_name in phase_a_capability_reasons
    }
    phase_a_non_blocking_capability_errors: dict[str, str] = {
        capability_name: phase_a_capability_reasons[capability_name]
        for capability_name in phase_a_non_blocking_degraded_capabilities
        if capability_name in phase_a_capability_reasons
    }
    ready = (
        phase_a_status == PHASE_STATUS_HEALTHY
        and not phase_a_blocking_failed_capabilities
        and phase_b_status != PHASE_STATUS_DEGRADED
        and not failed_platforms
    )

    return (
        jsonify(
            {
                "status": "ready" if ready else "not_ready",
                "ready": ready,
                "phase_a_status": phase_a_status,
                "phase_a_error": phase_a_error,
                "phase_a_capability_statuses": phase_a_capability_statuses,
                "phase_a_capability_errors": phase_a_capability_errors,
                "phase_a_capability_reasons": phase_a_capability_reasons,
                "phase_a_failed_capabilities": phase_a_failed_capabilities,
                "phase_a_blocking_failed_capabilities": (
                    phase_a_blocking_failed_capabilities
                ),
                "phase_a_non_blocking_degraded_capabilities": (
                    phase_a_non_blocking_degraded_capabilities
                ),
                "phase_a_blocking_capability_errors": phase_a_blocking_capability_errors,
                "phase_a_non_blocking_capability_errors": (
                    phase_a_non_blocking_capability_errors
                ),
                "phase_b_status": phase_b_status,
                "phase_b_error": phase_b_error,
                "critical_platforms": critical_platforms,
                "failed_platforms": failed_platforms,
                "reasons": reasons,
            }
        ),
        200 if ready else 503,
    )
