"""Strict runtime config contract checks for line-enabled core deployments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mugen.core.utility.platform_runtime_profile import get_platform_profile_dicts


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


def _iter_line_profile_configs(
    config: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    line_cfg = _require_table(config.get("line"), path="line")
    raw_profiles = line_cfg.get("profiles")
    if isinstance(raw_profiles, list) and not raw_profiles:
        raise RuntimeError(
            "Invalid configuration: line.profiles must be a non-empty array."
        )

    profiles_enabled = isinstance(raw_profiles, list) and bool(raw_profiles)
    profile_keys: set[str] = set()
    path_tokens: set[str] = set()
    profile_configs: list[tuple[str, Mapping[str, Any]]] = []

    for index, profile_cfg in enumerate(
        get_platform_profile_dicts(config, platform="line")
    ):
        profile_path = f"line.profiles[{index}]" if profiles_enabled else "line"
        profile_key = _require_non_empty_string(
            value=profile_cfg.get("key"),
            path=f"{profile_path}.key",
        )
        if profile_key in profile_keys:
            raise RuntimeError(
                "Invalid configuration: line profile keys must be unique."
            )
        profile_keys.add(profile_key)

        webhook_cfg = _require_table(
            profile_cfg.get("webhook"),
            path=f"{profile_path}.webhook",
        )
        path_token = _require_non_empty_string(
            value=webhook_cfg.get("path_token"),
            path=f"{profile_path}.webhook.path_token",
        )
        if path_token in path_tokens:
            raise RuntimeError(
                "Invalid configuration: line webhook path tokens must be unique."
            )
        path_tokens.add(path_token)
        profile_configs.append((profile_path, profile_cfg))

    return profile_configs


def validate_line_enabled_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate strict line runtime config when line platform is enabled."""
    line_cfg = _require_table(config.get("line"), path="line")
    profile_configs = _iter_line_profile_configs(config)

    webhook_cfg = _require_table(line_cfg.get("webhook"), path="line.webhook")
    _require_positive_int(
        value=webhook_cfg.get("dedupe_ttl_seconds"),
        path="line.webhook.dedupe_ttl_seconds",
    )

    api_cfg = _require_table(
        line_cfg.get("api"),
        path="line.api",
    )
    _require_non_empty_string(
        value=api_cfg.get("base_url"),
        path="line.api.base_url",
    )
    _require_positive_number(
        value=api_cfg.get("timeout_seconds"),
        path="line.api.timeout_seconds",
    )
    _require_positive_int(
        value=api_cfg.get("max_api_retries"),
        path="line.api.max_api_retries",
    )
    _require_nonnegative_number(
        value=api_cfg.get("retry_backoff_seconds"),
        path="line.api.retry_backoff_seconds",
    )

    media_cfg = _require_table(
        line_cfg.get("media"),
        path="line.media",
    )
    _require_non_empty_string_list(
        value=media_cfg.get("allowed_mimetypes"),
        path="line.media.allowed_mimetypes",
    )
    _require_positive_int(
        value=media_cfg.get("max_download_bytes"),
        path="line.media.max_download_bytes",
    )

    typing_cfg = _require_table(
        line_cfg.get("typing"),
        path="line.typing",
    )
    _require_bool(
        value=typing_cfg.get("enabled"),
        path="line.typing.enabled",
    )

    for profile_path, profile_cfg in profile_configs:
        channel_cfg = _require_table(
            profile_cfg.get("channel"),
            path=f"{profile_path}.channel",
        )
        _require_non_empty_string(
            value=channel_cfg.get("access_token"),
            path=f"{profile_path}.channel.access_token",
        )
        _require_non_empty_string(
            value=channel_cfg.get("secret"),
            path=f"{profile_path}.channel.secret",
        )
