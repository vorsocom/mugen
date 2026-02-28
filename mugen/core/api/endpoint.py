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
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
    PHASE_STATUS_STOPPED,
    get_bootstrap_state,
)
from mugen.core.api import api

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


def _phase_b_starting_within_grace(
    *,
    phase_b_status: str,
    phase_b_started_at: object,
    readiness_grace_seconds: float,
) -> bool:
    if phase_b_status != PHASE_STATUS_STARTING:
        return False
    if readiness_grace_seconds <= 0:
        return False
    try:
        started_at = float(phase_b_started_at)
    except (TypeError, ValueError):
        return False
    elapsed_seconds = perf_counter() - started_at
    return elapsed_seconds < readiness_grace_seconds


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


def _resolve_failed_platforms(
    *,
    critical_platforms: list[str],
    platform_statuses: dict[str, str],
    platform_errors: dict[str, Any],
    ignore_starting: bool,
    degrade_on_critical_exit: bool,
) -> tuple[list[str], dict[str, str]]:
    failed: list[str] = []
    reasons: dict[str, str] = {}
    for platform in critical_platforms:
        status = str(platform_statuses.get(platform, PHASE_STATUS_STARTING) or "")
        if status == PHASE_STATUS_HEALTHY:
            continue
        if ignore_starting and status == PHASE_STATUS_STARTING:
            continue
        if status == PHASE_STATUS_STOPPED and degrade_on_critical_exit is not True:
            continue

        failed.append(platform)
        reason = platform_errors.get(platform)
        if reason in [None, ""]:
            if status == PHASE_STATUS_STARTING:
                reason = "platform still starting"
            elif status == PHASE_STATUS_STOPPED:
                reason = "platform stopped"
            elif status == PHASE_STATUS_DEGRADED:
                reason = "platform degraded"
            else:
                reason = f"platform status={status}"
        reasons[platform] = str(reason)
    return failed, reasons


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
    phase_b_status = status["phase_b_status"]
    phase_b_error = status["phase_b_error"]
    readiness_grace_seconds = _parse_nonnegative_float(
        status["phase_b_readiness_grace_seconds"],
        default=0.0,
    )
    ignore_starting = _phase_b_starting_within_grace(
        phase_b_status=phase_b_status,
        phase_b_started_at=status["phase_b_started_at"],
        readiness_grace_seconds=readiness_grace_seconds,
    )
    degrade_on_critical_exit = _parse_bool(
        status["phase_b_degrade_on_critical_exit"],
        default=True,
    )
    critical_platforms = status["phase_b_critical_platforms"]
    if not isinstance(critical_platforms, list):
        critical_platforms = []
    critical_platforms = [
        str(platform).strip().lower()
        for platform in critical_platforms
        if str(platform).strip() != ""
    ]

    platform_statuses_raw = status["phase_b_platform_statuses"]
    platform_statuses: dict[str, str] = {}
    if isinstance(platform_statuses_raw, dict):
        for platform, platform_status in platform_statuses_raw.items():
            normalized_platform = str(platform).strip().lower()
            if normalized_platform == "":
                continue
            platform_statuses[normalized_platform] = str(platform_status or "")

    platform_errors_raw = status["phase_b_platform_errors"]
    platform_errors: dict[str, Any] = {}
    if isinstance(platform_errors_raw, dict):
        for platform, error in platform_errors_raw.items():
            normalized_platform = str(platform).strip().lower()
            if normalized_platform == "":
                continue
            platform_errors[normalized_platform] = error

    failed_platforms, reasons = _resolve_failed_platforms(
        critical_platforms=critical_platforms,
        platform_statuses=platform_statuses,
        platform_errors=platform_errors,
        ignore_starting=ignore_starting,
        degrade_on_critical_exit=degrade_on_critical_exit,
    )
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
