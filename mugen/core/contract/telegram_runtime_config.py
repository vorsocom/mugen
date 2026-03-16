"""Strict runtime config contract checks for telegram-enabled core deployments."""

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


def validate_telegram_enabled_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate strict telegram runtime config when telegram platform is enabled."""
    telegram_cfg = _require_table(config.get("telegram"), path="telegram")

    webhook_cfg = _require_table(telegram_cfg.get("webhook"), path="telegram.webhook")
    _require_positive_int(
        value=webhook_cfg.get("dedupe_ttl_seconds"),
        path="telegram.webhook.dedupe_ttl_seconds",
    )

    api_cfg = _require_table(
        telegram_cfg.get("api"),
        path="telegram.api",
    )
    _require_non_empty_string(
        value=api_cfg.get("base_url"),
        path="telegram.api.base_url",
    )
    _require_positive_number(
        value=api_cfg.get("timeout_seconds"),
        path="telegram.api.timeout_seconds",
    )
    _require_positive_int(
        value=api_cfg.get("max_api_retries"),
        path="telegram.api.max_api_retries",
    )
    _require_nonnegative_number(
        value=api_cfg.get("retry_backoff_seconds"),
        path="telegram.api.retry_backoff_seconds",
    )

    media_cfg = _require_table(
        telegram_cfg.get("media"),
        path="telegram.media",
    )
    _require_non_empty_string_list(
        value=media_cfg.get("allowed_mimetypes"),
        path="telegram.media.allowed_mimetypes",
    )
    _require_positive_int(
        value=media_cfg.get("max_download_bytes"),
        path="telegram.media.max_download_bytes",
    )

    typing_cfg = _require_table(
        telegram_cfg.get("typing"),
        path="telegram.typing",
    )
    _require_bool(
        value=typing_cfg.get("enabled"),
        path="telegram.typing.enabled",
    )
