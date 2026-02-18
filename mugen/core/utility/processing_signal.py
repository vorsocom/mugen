"""Utilities for normalized processing/thinking signal handling."""

__all__ = [
    "PROCESSING_SIGNAL_THINKING",
    "PROCESSING_STATE_START",
    "PROCESSING_STATE_STOP",
    "PROCESSING_STATES",
    "normalize_processing_state",
    "build_thinking_signal_payload",
]

from typing import Any


PROCESSING_SIGNAL_THINKING = "thinking"

PROCESSING_STATE_START = "start"

PROCESSING_STATE_STOP = "stop"

PROCESSING_STATES = {
    PROCESSING_STATE_START,
    PROCESSING_STATE_STOP,
}


def normalize_processing_state(state: str) -> str:
    """Normalize and validate a processing signal state."""
    normalized = str(state).strip().lower()
    if normalized not in PROCESSING_STATES:
        raise ValueError(f"Unsupported processing signal state: {state!r}.")
    return normalized


def build_thinking_signal_payload(
    *,
    state: str,
    job_id: str | None = None,
    conversation_id: str | None = None,
    client_message_id: str | None = None,
    sender: str | None = None,
) -> dict[str, Any]:
    """Build a canonical thinking-signal payload."""
    return {
        "signal": PROCESSING_SIGNAL_THINKING,
        "state": normalize_processing_state(state),
        "job_id": job_id,
        "conversation_id": conversation_id,
        "client_message_id": client_message_id,
        "sender": sender,
    }
