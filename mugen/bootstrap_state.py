"""Bootstrap lifecycle phase state keys and status helpers."""

from __future__ import annotations

from quart import Quart

MUGEN_EXTENSION_KEY = "mugen"
BOOTSTRAP_STATE_KEY = "bootstrap"
PHASE_A_STATUS_KEY = "phase_a_status"
PHASE_B_STATUS_KEY = "phase_b_status"
PHASE_B_ERROR_KEY = "phase_b_error"
PHASE_B_STARTED_AT_KEY = "phase_b_started_at"
PHASE_B_PLATFORM_STATUSES_KEY = "platform_statuses"
PHASE_B_PLATFORM_ERRORS_KEY = "platform_errors"
SHUTDOWN_REQUESTED_KEY = "shutdown_requested"

PHASE_STATUS_STARTING = "starting"
PHASE_STATUS_HEALTHY = "healthy"
PHASE_STATUS_DEGRADED = "degraded"
PHASE_STATUS_STOPPED = "stopped"


def get_bootstrap_state(app: Quart) -> dict:
    """Get mutable bootstrap state storage from app extensions."""
    mugen_state = app.extensions.setdefault(MUGEN_EXTENSION_KEY, {})
    return mugen_state.setdefault(BOOTSTRAP_STATE_KEY, {})
