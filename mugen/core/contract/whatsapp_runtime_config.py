"""Strict runtime config contract checks for whatsapp-enabled core deployments."""

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


def _require_string_list(*, value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(
            f"Invalid configuration: {path} must be an array of strings."
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


def _require_nonnegative_int(*, value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(
            f"Invalid configuration: {path} must be a non-negative integer."
        )
    if value < 0:
        raise RuntimeError(
            f"Invalid configuration: {path} must be a non-negative integer."
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


def _beta_is_active(config: Mapping[str, Any]) -> bool:
    mugen_cfg = config.get("mugen")
    if not isinstance(mugen_cfg, Mapping):
        return False
    beta_cfg = mugen_cfg.get("beta")
    if not isinstance(beta_cfg, Mapping):
        return False
    return beta_cfg.get("active") is True


def validate_whatsapp_enabled_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate strict whatsapp runtime config when whatsapp platform is enabled."""
    whatsapp_cfg = _require_table(config.get("whatsapp"), path="whatsapp")

    graphapi_cfg = _require_table(
        whatsapp_cfg.get("graphapi"),
        path="whatsapp.graphapi",
    )
    _require_non_empty_string(
        value=graphapi_cfg.get("base_url"),
        path="whatsapp.graphapi.base_url",
    )
    _require_non_empty_string(
        value=graphapi_cfg.get("version"),
        path="whatsapp.graphapi.version",
    )
    _require_positive_number(
        value=graphapi_cfg.get("timeout_seconds"),
        path="whatsapp.graphapi.timeout_seconds",
    )
    _require_positive_int(
        value=graphapi_cfg.get("max_download_bytes"),
        path="whatsapp.graphapi.max_download_bytes",
    )
    _require_bool(
        value=graphapi_cfg.get("typing_indicator_enabled"),
        path="whatsapp.graphapi.typing_indicator_enabled",
    )
    max_api_retries = graphapi_cfg.get("max_api_retries")
    if max_api_retries is not None:
        _require_nonnegative_int(
            value=max_api_retries,
            path="whatsapp.graphapi.max_api_retries",
        )
    retry_backoff_seconds = graphapi_cfg.get("retry_backoff_seconds")
    if retry_backoff_seconds is not None:
        _require_nonnegative_number(
            value=retry_backoff_seconds,
            path="whatsapp.graphapi.retry_backoff_seconds",
        )

    servers_cfg = _require_table(
        whatsapp_cfg.get("servers"),
        path="whatsapp.servers",
    )
    verify_ip = _require_bool(
        value=servers_cfg.get("verify_ip"),
        path="whatsapp.servers.verify_ip",
    )
    if verify_ip is True:
        _require_non_empty_string(
            value=servers_cfg.get("allowed"),
            path="whatsapp.servers.allowed",
        )
    _require_bool(
        value=servers_cfg.get("trust_forwarded_for"),
        path="whatsapp.servers.trust_forwarded_for",
    )

    webhook_cfg = _require_table(
        whatsapp_cfg.get("webhook"),
        path="whatsapp.webhook",
    )
    _require_positive_int(
        value=webhook_cfg.get("dedupe_ttl_seconds"),
        path="whatsapp.webhook.dedupe_ttl_seconds",
    )

    if _beta_is_active(config):
        beta_cfg = _require_table(
            whatsapp_cfg.get("beta"),
            path="whatsapp.beta",
        )
        _require_string_list(
            value=beta_cfg.get("users"),
            path="whatsapp.beta.users",
        )
