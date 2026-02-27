"""Implements API endpoints."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from quart import current_app, jsonify

from mugen.bootstrap_state import (
    PHASE_A_STATUS_KEY,
    PHASE_B_ERROR_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
    get_bootstrap_state,
)
from mugen.core.api import api

_PHASE_B_READINESS_GRACE_KEY = "phase_b_readiness_grace_seconds"
_PHASE_B_CRITICAL_PLATFORMS_KEY = "phase_b_critical_platforms"


def _resolve_bootstrap_status() -> dict[str, Any]:
    state = get_bootstrap_state(current_app)
    return {
        "phase_a_status": str(state.get(PHASE_A_STATUS_KEY, "") or ""),
        "phase_b_status": str(state.get(PHASE_B_STATUS_KEY, "") or ""),
        "phase_b_error": state.get(PHASE_B_ERROR_KEY),
        "phase_b_started_at": state.get(PHASE_B_STARTED_AT_KEY),
        "phase_b_readiness_grace_seconds": state.get(_PHASE_B_READINESS_GRACE_KEY, 0.0),
        "phase_b_critical_platforms": state.get(_PHASE_B_CRITICAL_PLATFORMS_KEY, []),
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
    phase_b_status = status["phase_b_status"]
    phase_b_error = status["phase_b_error"]
    phase_b_started_at = status["phase_b_started_at"]

    ready = phase_a_status == PHASE_STATUS_HEALTHY and phase_b_status != PHASE_STATUS_DEGRADED

    if phase_b_status == PHASE_STATUS_STARTING:
        grace_seconds = float(status["phase_b_readiness_grace_seconds"] or 0.0)
        critical_platforms = status["phase_b_critical_platforms"] or []
        elapsed = 0.0
        if phase_b_started_at is not None:
            try:
                elapsed = max(0.0, perf_counter() - float(phase_b_started_at))
            except (TypeError, ValueError):
                elapsed = 0.0
        if critical_platforms and elapsed > grace_seconds:
            ready = False

    return (
        jsonify(
            {
                "status": "ready" if ready else "not_ready",
                "ready": ready,
                "phase_a_status": phase_a_status,
                "phase_b_status": phase_b_status,
                "phase_b_error": phase_b_error,
            }
        ),
        200 if ready else 503,
    )
