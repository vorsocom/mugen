"""Implements API endpoints."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from quart import current_app, jsonify

from mugen.bootstrap_state import (
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

_PHASE_B_READINESS_GRACE_KEY = "phase_b_readiness_grace_seconds"
_PHASE_B_CRITICAL_PLATFORMS_KEY = "phase_b_critical_platforms"
_PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY = "phase_b_degrade_on_critical_exit"


def _parse_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _parse_nonnegative_float(value: object, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def _normalize_platform_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for item in values:
        platform = str(item).strip().lower()
        if platform == "" or platform in normalized:
            continue
        normalized.append(platform)
    return normalized


def _resolve_bootstrap_status() -> dict[str, Any]:
    state = get_bootstrap_state(current_app)
    return {
        "phase_a_status": str(state.get(PHASE_A_STATUS_KEY, "") or ""),
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


@api.get("/core/health/live")
async def core_health_live():
    """Liveness health probe."""
    status = _resolve_bootstrap_status()
    return (
        jsonify(
            {
                "status": "live",
                "phase_a_status": status["phase_a_status"],
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
    readiness_grace_seconds = _parse_nonnegative_float(
        status["phase_b_readiness_grace_seconds"],
        default=0.0,
    )
    degrade_on_critical_exit = _parse_bool(
        status["phase_b_degrade_on_critical_exit"],
        default=True,
    )
    critical_platforms = _normalize_platform_list(status["phase_b_critical_platforms"])

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
            preserve_reported_degraded=True,
            default_critical_platforms_to_statuses=False,
            now_monotonic=perf_counter(),
        )
    )
    phase_b_status = health.phase_b_status
    phase_b_error = health.phase_b_error
    failed_platforms = health.failed_critical_platforms
    reasons = health.reasons
    ready = (
        phase_a_status == PHASE_STATUS_HEALTHY
        and phase_b_status != PHASE_STATUS_DEGRADED
        and not failed_platforms
    )

    return (
        jsonify(
            {
                "status": "ready" if ready else "not_ready",
                "ready": ready,
                "phase_a_status": phase_a_status,
                "phase_b_status": phase_b_status,
                "phase_b_error": phase_b_error,
                "critical_platforms": critical_platforms,
                "failed_platforms": failed_platforms,
                "reasons": reasons,
            }
        ),
        200 if ready else 503,
    )
