"""Strict runtime config contract checks for whatsapp-enabled core deployments."""

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


def _iter_whatsapp_profile_configs(
    config: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    whatsapp_cfg = _require_table(config.get("whatsapp"), path="whatsapp")
    raw_profiles = whatsapp_cfg.get("profiles")
    if isinstance(raw_profiles, list) and not raw_profiles:
        raise RuntimeError(
            "Invalid configuration: whatsapp.profiles must be a non-empty array."
        )

    profiles_enabled = isinstance(raw_profiles, list) and bool(raw_profiles)
    profile_keys: set[str] = set()
    phone_number_ids: set[str] = set()
    profile_configs: list[tuple[str, Mapping[str, Any]]] = []

    for index, profile_cfg in enumerate(
        get_platform_profile_dicts(config, platform="whatsapp")
    ):
        profile_path = (
            f"whatsapp.profiles[{index}]"
            if profiles_enabled
            else "whatsapp"
        )
        profile_key = _require_non_empty_string(
            value=profile_cfg.get("key"),
            path=f"{profile_path}.key",
        )
        if profile_key in profile_keys:
            raise RuntimeError(
                "Invalid configuration: whatsapp profile keys must be unique."
            )
        profile_keys.add(profile_key)

        business_cfg = _require_table(
            profile_cfg.get("business"),
            path=f"{profile_path}.business",
        )
        phone_number_id = _require_non_empty_string(
            value=business_cfg.get("phone_number_id"),
            path=f"{profile_path}.business.phone_number_id",
        )
        if phone_number_id in phone_number_ids:
            raise RuntimeError(
                "Invalid configuration: whatsapp business.phone_number_id values "
                "must be unique."
            )
        phone_number_ids.add(phone_number_id)
        profile_configs.append((profile_path, profile_cfg))

    return profile_configs


def validate_whatsapp_enabled_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate strict whatsapp runtime config when whatsapp platform is enabled."""
    whatsapp_cfg = _require_table(config.get("whatsapp"), path="whatsapp")
    profile_configs = _iter_whatsapp_profile_configs(config)

    graphapi_cfg = _require_table(
        whatsapp_cfg.get("graphapi"),
        path="whatsapp.graphapi",
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
    _require_non_empty_string(
        value=webhook_cfg.get("verification_token"),
        path="whatsapp.webhook.verification_token",
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

    for profile_path, profile_cfg in profile_configs:
        app_cfg = _require_table(
            profile_cfg.get("app"),
            path=f"{profile_path}.app",
        )
        _require_non_empty_string(
            value=app_cfg.get("secret"),
            path=f"{profile_path}.app.secret",
        )

        profile_graphapi_cfg = _require_table(
            profile_cfg.get("graphapi"),
            path=f"{profile_path}.graphapi",
        )
        _require_non_empty_string(
            value=profile_graphapi_cfg.get("access_token"),
            path=f"{profile_path}.graphapi.access_token",
        )
        _require_non_empty_string(
            value=profile_graphapi_cfg.get("base_url"),
            path=f"{profile_path}.graphapi.base_url",
        )
        _require_non_empty_string(
            value=profile_graphapi_cfg.get("version"),
            path=f"{profile_path}.graphapi.version",
        )
