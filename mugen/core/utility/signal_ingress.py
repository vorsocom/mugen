"""Shared helpers for Signal ingress envelope normalization."""

from __future__ import annotations

__all__ = [
    "resolve_signal_account_number",
    "signal_envelope",
    "signal_event_id",
    "signal_event_type",
    "signal_sender",
]

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any


def _nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized != "" else None


def signal_envelope(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    envelope = params.get("envelope")
    return envelope if isinstance(envelope, dict) else None


def signal_sender(envelope: Mapping[str, Any]) -> str | None:
    for key in ("sourceNumber", "sourceUuid", "source"):
        sender = _nonempty_text(envelope.get(key))
        if sender is not None:
            return sender
    return None


def signal_event_id(envelope: Mapping[str, Any]) -> str | None:
    timestamp = envelope.get("timestamp")
    if isinstance(timestamp, bool):
        return None
    if not isinstance(timestamp, (int, float)):
        return None
    source = signal_sender(envelope)
    if source is not None:
        return f"{source}:{int(timestamp)}"
    return str(int(timestamp))


def signal_event_type(envelope: Mapping[str, Any]) -> str:
    data_message = envelope.get("dataMessage")
    receipt_message = envelope.get("receiptMessage")
    typing_message = envelope.get("typingMessage")
    if isinstance(data_message, dict):
        if isinstance(data_message.get("reaction"), dict):
            return "reaction"
        return "message"
    if isinstance(receipt_message, dict):
        return "receipt"
    if isinstance(typing_message, dict):
        return "typing"
    return "event"


def resolve_signal_account_number(
    *,
    payload: Mapping[str, Any] | None = None,
    config: SimpleNamespace | None = None,
) -> str | None:
    if isinstance(payload, Mapping):
        account_number = _nonempty_text(payload.get("account_number"))
        if account_number is not None:
            return account_number
        provider_context = payload.get("provider_context")
        if isinstance(provider_context, Mapping):
            account_number = _nonempty_text(provider_context.get("account_number"))
            if account_number is not None:
                return account_number

    if config is None:
        return None

    signal_cfg = getattr(config, "signal", SimpleNamespace())
    account_cfg = getattr(signal_cfg, "account", SimpleNamespace())
    return _nonempty_text(getattr(account_cfg, "number", None))
