"""Strict runtime config contract checks for wechat-enabled core deployments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_WECHAT_PROVIDER_OFFICIAL_ACCOUNT = "official_account"
_WECHAT_PROVIDER_WECOM = "wecom"
_ALLOWED_PROVIDERS = frozenset(
    {
        _WECHAT_PROVIDER_OFFICIAL_ACCOUNT,
        _WECHAT_PROVIDER_WECOM,
    }
)


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


def validate_wechat_enabled_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate strict wechat runtime config when wechat platform is enabled."""
    wechat_cfg = _require_table(config.get("wechat"), path="wechat")

    webhook_cfg = _require_table(wechat_cfg.get("webhook"), path="wechat.webhook")
    _require_positive_int(
        value=webhook_cfg.get("dedupe_ttl_seconds"),
        path="wechat.webhook.dedupe_ttl_seconds",
    )

    api_cfg = _require_table(
        wechat_cfg.get("api"),
        path="wechat.api",
    )
    _require_positive_number(
        value=api_cfg.get("timeout_seconds"),
        path="wechat.api.timeout_seconds",
    )
    _require_positive_int(
        value=api_cfg.get("max_api_retries"),
        path="wechat.api.max_api_retries",
    )
    _require_nonnegative_number(
        value=api_cfg.get("retry_backoff_seconds"),
        path="wechat.api.retry_backoff_seconds",
    )
    _require_positive_int(
        value=api_cfg.get("max_download_bytes"),
        path="wechat.api.max_download_bytes",
    )

    typing_cfg = _require_table(
        wechat_cfg.get("typing"),
        path="wechat.typing",
    )
    _require_bool(
        value=typing_cfg.get("enabled"),
        path="wechat.typing.enabled",
    )
