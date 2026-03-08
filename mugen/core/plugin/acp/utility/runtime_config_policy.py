"""Shared policy helpers for tenant-editable runtime settings and secrets."""

from __future__ import annotations

__all__ = [
    "ALLOWED_MESSAGING_SECRET_REF_PATHS",
    "ALLOWED_MESSAGING_SETTINGS_PATHS",
    "ALLOWED_OPS_CONNECTOR_DEFAULT_PATHS",
    "normalize_json_object",
    "normalize_messaging_platform_key",
    "normalize_runtime_config_category",
    "normalize_runtime_config_profile_key",
    "normalize_runtime_config_settings",
    "normalize_secret_ref_map",
    "normalize_tenant_messaging_settings",
]

from collections.abc import Mapping
from typing import Any
import uuid


ALLOWED_MESSAGING_SECRET_REF_PATHS: dict[str, frozenset[tuple[str, ...]]] = {
    "line": frozenset(
        {
            ("channel", "access_token"),
            ("channel", "secret"),
        }
    ),
    "matrix": frozenset({("client", "password")}),
    "signal": frozenset({("api", "bearer_token")}),
    "telegram": frozenset(
        {
            ("bot", "token"),
            ("webhook", "secret_token"),
        }
    ),
    "wechat": frozenset(
        {
            ("webhook", "signature_token"),
            ("webhook", "aes_key"),
            ("official_account", "app_secret"),
            ("wecom", "corp_secret"),
        }
    ),
    "whatsapp": frozenset(
        {
            ("app", "secret"),
            ("graphapi", "access_token"),
            ("webhook", "verification_token"),
        }
    ),
}

ALLOWED_MESSAGING_SETTINGS_PATHS: dict[str, frozenset[tuple[str, ...]]] = {
    "line": frozenset(),
    "matrix": frozenset(
        {
            ("homeserver",),
            ("client", "device"),
            ("room_id",),
        }
    ),
    "signal": frozenset({("api", "base_url")}),
    "telegram": frozenset(),
    "wechat": frozenset(
        {
            ("webhook", "aes_enabled"),
            ("official_account", "app_id"),
            ("wecom", "corp_id"),
            ("wecom", "agent_id"),
        }
    ),
    "whatsapp": frozenset({("app", "id")}),
}

ALLOWED_OPS_CONNECTOR_DEFAULT_PATHS = frozenset(
    {
        ("timeout_seconds_default",),
        ("max_retries_default",),
        ("retry_backoff_seconds_default",),
        ("retry_status_codes_default",),
        ("redacted_keys",),
    }
)

_ALLOWED_MESSAGING_PLATFORMS = frozenset(ALLOWED_MESSAGING_SETTINGS_PATHS)
_ALLOWED_RUNTIME_CATEGORIES = frozenset(
    {
        "messaging.platform_defaults",
        "ops_connector.defaults",
    }
)


def _normalize_required_text(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if text == "":
        raise RuntimeError(f"{field_name} must be non-empty.")
    return text


def _normalize_key(value: object, *, field_name: str) -> str:
    text = _normalize_required_text(value, field_name=field_name)
    return text.lower()


def normalize_json_object(value: object, *, field_name: str) -> dict[str, Any]:
    """Normalize a JSON-object payload using lower-cased object keys."""
    if value is None:
        return {}
    if isinstance(value, Mapping) is not True:
        raise RuntimeError(f"{field_name} must be a JSON object.")
    return _normalize_object(value, field_name=field_name)


def _normalize_object(value: Mapping[str, Any], *, field_name: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = _normalize_key(raw_key, field_name=field_name)
        if key in output:
            raise RuntimeError(f"{field_name} contains duplicate key {key!r}.")
        output[key] = _normalize_json_value(
            raw_value,
            field_name=f"{field_name}.{key}",
        )
    return output


def _normalize_json_value(value: Any, *, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return _normalize_object(value, field_name=field_name)
    if isinstance(value, list):
        return [
            _normalize_json_value(item, field_name=f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def _iter_leaf_paths(
    payload: Mapping[str, Any],
    *,
    prefix: tuple[str, ...] = (),
):
    for raw_key, raw_value in payload.items():
        key = str(raw_key)
        path = prefix + (key,)
        if isinstance(raw_value, Mapping):
            if raw_value:
                yield from _iter_leaf_paths(raw_value, prefix=path)
                continue
            yield path, raw_value
            continue
        yield path, raw_value


def _path_text(path: tuple[str, ...]) -> str:
    return ".".join(path)


def normalize_messaging_platform_key(value: object) -> str:
    """Normalize and validate a supported messaging platform key."""
    platform_key = _normalize_key(value, field_name="PlatformKey")
    if platform_key not in _ALLOWED_MESSAGING_PLATFORMS:
        raise RuntimeError(
            "PlatformKey must be one of "
            f"{', '.join(sorted(_ALLOWED_MESSAGING_PLATFORMS))}."
        )
    return platform_key


def _validate_allowed_leaf_paths(
    payload: Mapping[str, Any],
    *,
    allowed_paths: frozenset[tuple[str, ...]],
    field_name: str,
) -> dict[str, Any]:
    for path, _value in _iter_leaf_paths(payload):
        if path not in allowed_paths:
            raise RuntimeError(
                f"{field_name} path {_path_text(path)!r} is not allowed."
            )
    return dict(payload)


def normalize_tenant_messaging_settings(
    *,
    platform_key: object,
    value: object,
) -> dict[str, Any]:
    """Normalize ACP-owned tenant messaging settings for a platform."""
    normalized_platform_key = normalize_messaging_platform_key(platform_key)
    payload = normalize_json_object(value, field_name="Settings")
    return _validate_allowed_leaf_paths(
        payload,
        allowed_paths=ALLOWED_MESSAGING_SETTINGS_PATHS[normalized_platform_key],
        field_name="Settings",
    )


def normalize_secret_ref_map(
    *,
    platform_key: object,
    value: object,
) -> dict[str, str]:
    """Normalize and validate ACP secret-ref maps for one messaging platform."""
    normalized_platform_key = normalize_messaging_platform_key(platform_key)
    if value is None:
        payload = {}
    elif isinstance(value, Mapping):
        payload = {str(k): v for k, v in value.items()}
    else:
        raise RuntimeError("SecretRefs must be a JSON object.")
    normalized: dict[str, str] = {}
    allowed_paths = ALLOWED_MESSAGING_SECRET_REF_PATHS[normalized_platform_key]
    for raw_key, raw_value in payload.items():
        path = tuple(
            _normalize_key(part, field_name="SecretRefs key")
            for part in str(raw_key).split(".")
            if str(part).strip()
        )
        if not path:
            raise RuntimeError("SecretRefs key must be non-empty.")
        if path not in allowed_paths:
            raise RuntimeError(
                f"SecretRefs path {_path_text(path)!r} is not allowed."
            )
        dotted_path = _path_text(path)
        try:
            normalized[dotted_path] = str(uuid.UUID(str(raw_value).strip()))
        except (AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"SecretRefs.{dotted_path} must be a valid KeyRef UUID."
            ) from exc
    return normalized


def normalize_runtime_config_category(value: object) -> str:
    """Normalize and validate a supported runtime config category."""
    category = _normalize_key(value, field_name="Category")
    if category not in _ALLOWED_RUNTIME_CATEGORIES:
        raise RuntimeError(
            "Category must be one of "
            f"{', '.join(sorted(_ALLOWED_RUNTIME_CATEGORIES))}."
        )
    return category


def normalize_runtime_config_profile_key(*, category: object, value: object) -> str:
    """Normalize a runtime config profile key within a category."""
    normalized_category = normalize_runtime_config_category(category)
    profile_key = _normalize_key(value, field_name="ProfileKey")
    if normalized_category == "messaging.platform_defaults":
        return normalize_messaging_platform_key(profile_key)
    if normalized_category == "ops_connector.defaults" and profile_key != "default":
        raise RuntimeError(
            "ProfileKey must be 'default' for category 'ops_connector.defaults'."
        )
    return profile_key


def normalize_runtime_config_settings(
    *,
    category: object,
    profile_key: object,
    value: object,
) -> dict[str, Any]:
    """Normalize and validate runtime config profile settings."""
    normalized_category = normalize_runtime_config_category(category)
    normalized_profile_key = normalize_runtime_config_profile_key(
        category=normalized_category,
        value=profile_key,
    )
    payload = normalize_json_object(value, field_name="SettingsJson")

    if normalized_category == "messaging.platform_defaults":
        return _validate_allowed_leaf_paths(
            payload,
            allowed_paths=ALLOWED_MESSAGING_SETTINGS_PATHS[
                normalized_profile_key
            ],
            field_name="SettingsJson",
        )

    return _validate_allowed_leaf_paths(
        payload,
        allowed_paths=ALLOWED_OPS_CONNECTOR_DEFAULT_PATHS,
        field_name="SettingsJson",
    )
