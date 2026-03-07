"""Strict runtime config contract checks for wechat-enabled core deployments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mugen.core.utility.platform_runtime_profile import get_platform_profile_dicts


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


def _iter_wechat_profile_configs(
    config: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any], str]]:
    wechat_cfg = _require_table(config.get("wechat"), path="wechat")
    raw_profiles = wechat_cfg.get("profiles")
    if isinstance(raw_profiles, list) and not raw_profiles:
        raise RuntimeError(
            "Invalid configuration: wechat.profiles must be a non-empty array."
        )

    profiles_enabled = isinstance(raw_profiles, list) and bool(raw_profiles)
    profile_keys: set[str] = set()
    path_tokens: set[str] = set()
    profile_configs: list[tuple[str, Mapping[str, Any], str]] = []

    for index, profile_cfg in enumerate(
        get_platform_profile_dicts(config, platform="wechat")
    ):
        profile_path = f"wechat.profiles[{index}]" if profiles_enabled else "wechat"
        profile_key = _require_non_empty_string(
            value=profile_cfg.get("key"),
            path=f"{profile_path}.key",
        )
        if profile_key in profile_keys:
            raise RuntimeError(
                "Invalid configuration: wechat profile keys must be unique."
            )
        profile_keys.add(profile_key)

        provider = _require_non_empty_string(
            value=profile_cfg.get("provider"),
            path=f"{profile_path}.provider",
        ).lower()
        if provider not in _ALLOWED_PROVIDERS:
            supported = ", ".join(sorted(_ALLOWED_PROVIDERS))
            raise RuntimeError(
                f"Invalid configuration: {profile_path}.provider "
                f"must be one of: {supported}."
            )

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
                "Invalid configuration: wechat webhook path tokens must be unique."
            )
        path_tokens.add(path_token)
        profile_configs.append((profile_path, profile_cfg, provider))

    return profile_configs


def validate_wechat_enabled_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate strict wechat runtime config when wechat platform is enabled."""
    wechat_cfg = _require_table(config.get("wechat"), path="wechat")
    profile_configs = _iter_wechat_profile_configs(config)

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

    for profile_path, profile_cfg, provider in profile_configs:
        profile_webhook_cfg = _require_table(
            profile_cfg.get("webhook"),
            path=f"{profile_path}.webhook",
        )
        _require_non_empty_string(
            value=profile_webhook_cfg.get("signature_token"),
            path=f"{profile_path}.webhook.signature_token",
        )
        aes_enabled = _require_bool(
            value=profile_webhook_cfg.get("aes_enabled"),
            path=f"{profile_path}.webhook.aes_enabled",
        )
        if aes_enabled is True:
            _require_non_empty_string(
                value=profile_webhook_cfg.get("aes_key"),
                path=f"{profile_path}.webhook.aes_key",
            )

        if provider == _WECHAT_PROVIDER_OFFICIAL_ACCOUNT:
            oa_cfg = _require_table(
                profile_cfg.get("official_account"),
                path=f"{profile_path}.official_account",
            )
            _require_non_empty_string(
                value=oa_cfg.get("app_id"),
                path=f"{profile_path}.official_account.app_id",
            )
            _require_non_empty_string(
                value=oa_cfg.get("app_secret"),
                path=f"{profile_path}.official_account.app_secret",
            )
            continue

        wecom_cfg = _require_table(
            profile_cfg.get("wecom"),
            path=f"{profile_path}.wecom",
        )
        _require_non_empty_string(
            value=wecom_cfg.get("corp_id"),
            path=f"{profile_path}.wecom.corp_id",
        )
        _require_non_empty_string(
            value=wecom_cfg.get("corp_secret"),
            path=f"{profile_path}.wecom.corp_secret",
        )
        _require_positive_int(
            value=wecom_cfg.get("agent_id"),
            path=f"{profile_path}.wecom.agent_id",
        )
