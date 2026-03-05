"""Strict runtime config contract checks for signal-enabled core deployments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _require_table(parent: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(parent, Mapping):
        raise RuntimeError(f"Invalid configuration: {path} must be a table.")
    return parent


def _require_non_empty_string(*, value: object, path: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise RuntimeError(
            f"Invalid configuration: {path} is required and must be a non-empty string."
        )
    return value.strip()


def _require_non_empty_string_list(*, value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RuntimeError(
            f"Invalid configuration: {path} must be a non-empty array of strings."
        )
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item.strip() == "":
            raise RuntimeError(
                f"Invalid configuration: {path}[{index}] must be a non-empty string."
            )
        normalized.append(item.strip())
    return normalized


def _require_bool(*, value: object, path: str) -> bool:
    if isinstance(value, bool) is not True:
        raise RuntimeError(f"Invalid configuration: {path} must be a boolean.")
    return value


def _require_positive_int(*, value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(
            f"Invalid configuration: {path} must be a positive integer."
        )
    if value <= 0:
        raise RuntimeError(
            f"Invalid configuration: {path} must be a positive integer."
        )
    return value


def _require_positive_number(*, value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(
            f"Invalid configuration: {path} must be a positive number."
        )
    number = float(value)
    if number <= 0:
        raise RuntimeError(
            f"Invalid configuration: {path} must be a positive number."
        )
    return number


def _require_nonnegative_number(*, value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(
            f"Invalid configuration: {path} must be a non-negative number."
        )
    number = float(value)
    if number < 0:
        raise RuntimeError(
            f"Invalid configuration: {path} must be a non-negative number."
        )
    return number


def validate_signal_enabled_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate strict signal runtime config when signal platform is enabled."""
    signal_cfg = _require_table(config.get("signal"), path="signal")

    account_cfg = _require_table(signal_cfg.get("account"), path="signal.account")
    _require_non_empty_string(
        value=account_cfg.get("number"),
        path="signal.account.number",
    )

    api_cfg = _require_table(signal_cfg.get("api"), path="signal.api")
    _require_non_empty_string(
        value=api_cfg.get("base_url"),
        path="signal.api.base_url",
    )
    _require_non_empty_string(
        value=api_cfg.get("bearer_token"),
        path="signal.api.bearer_token",
    )
    _require_positive_number(
        value=api_cfg.get("timeout_seconds"),
        path="signal.api.timeout_seconds",
    )
    _require_positive_int(
        value=api_cfg.get("max_api_retries"),
        path="signal.api.max_api_retries",
    )
    _require_nonnegative_number(
        value=api_cfg.get("retry_backoff_seconds"),
        path="signal.api.retry_backoff_seconds",
    )

    receive_cfg = _require_table(signal_cfg.get("receive"), path="signal.receive")
    _require_positive_number(
        value=receive_cfg.get("heartbeat_seconds"),
        path="signal.receive.heartbeat_seconds",
    )
    _require_nonnegative_number(
        value=receive_cfg.get("reconnect_base_seconds"),
        path="signal.receive.reconnect_base_seconds",
    )
    _require_nonnegative_number(
        value=receive_cfg.get("reconnect_max_seconds"),
        path="signal.receive.reconnect_max_seconds",
    )
    _require_nonnegative_number(
        value=receive_cfg.get("reconnect_jitter_seconds"),
        path="signal.receive.reconnect_jitter_seconds",
    )
    _require_positive_int(
        value=receive_cfg.get("dedupe_ttl_seconds"),
        path="signal.receive.dedupe_ttl_seconds",
    )

    media_cfg = _require_table(signal_cfg.get("media"), path="signal.media")
    _require_non_empty_string_list(
        value=media_cfg.get("allowed_mimetypes"),
        path="signal.media.allowed_mimetypes",
    )
    _require_positive_int(
        value=media_cfg.get("max_download_bytes"),
        path="signal.media.max_download_bytes",
    )

    typing_cfg = _require_table(signal_cfg.get("typing"), path="signal.typing")
    _require_bool(
        value=typing_cfg.get("enabled"),
        path="signal.typing.enabled",
    )
