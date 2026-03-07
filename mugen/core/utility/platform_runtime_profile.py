"""Helpers for multi-profile messaging platform runtime configuration."""

from __future__ import annotations

__all__ = [
    "DEFAULT_RUNTIME_PROFILE_KEY",
    "build_config_namespace",
    "clone_config_with_platform_profile",
    "find_platform_runtime_profile_key",
    "get_active_runtime_profile_key",
    "identifier_configured_for_platform",
    "get_platform_profile_section",
    "get_platform_profile_dicts",
    "get_platform_profile_sections",
    "get_platform_runtime_profile_keys",
    "normalize_runtime_profile_key",
    "runtime_profile_scope",
    "runtime_profile_key_from_ingress_route",
]

from collections.abc import Mapping, Sequence
import copy
import contextlib
import contextvars
from types import SimpleNamespace
from typing import Any

from mugen.core.utility.collection.namespace import NamespaceConfig, to_namespace

DEFAULT_RUNTIME_PROFILE_KEY = "default"

_CONFIG_NAMESPACE_CONVERSION = NamespaceConfig(
    keep_raw=True,
    raw_attr="dict",
    add_aliases=False,
)

_WECHAT_PROVIDER_PATH = ("provider",)

_PLATFORM_IDENTIFIER_PATHS: dict[str, dict[str, tuple[str, ...]]] = {
    "line": {
        "path_token": ("webhook", "path_token"),
    },
    "matrix": {
        "recipient_user_id": ("client", "user"),
    },
    "signal": {
        "account_number": ("account", "number"),
    },
    "telegram": {
        "path_token": ("webhook", "path_token"),
        "secret_token": ("webhook", "secret_token"),
    },
    "wechat": {
        "path_token": ("webhook", "path_token"),
        "provider": _WECHAT_PROVIDER_PATH,
    },
    "whatsapp": {
        "phone_number_id": ("business", "phone_number_id"),
    },
}

_ACTIVE_RUNTIME_PROFILE_KEY: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("mugen_active_runtime_profile_key", default=None)
)


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_required_text(value: object, *, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise RuntimeError(f"Invalid configuration: {field_name} must be non-empty.")
    return normalized


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if (
            isinstance(value, Mapping)
            and isinstance(merged.get(key), Mapping)
        ):
            merged[key] = _deep_merge(dict(merged[key]), value)
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def _plain_data(value: Any) -> Any:
    if isinstance(value, SimpleNamespace):
        raw = getattr(value, "dict", None)
        if isinstance(raw, Mapping):
            return copy.deepcopy(dict(raw))

        output: dict[str, Any] = {}
        for key, item in vars(value).items():
            if key == "dict" or key.endswith("__"):
                continue
            output[key] = _plain_data(item)
        return output

    if isinstance(value, Mapping):
        return {
            str(key): _plain_data(item)
            for key, item in value.items()
        }

    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_plain_data(item) for item in value]

    return copy.deepcopy(value)


def build_config_namespace(config: Mapping[str, Any]) -> SimpleNamespace:
    """Convert a config mapping into the repo's runtime namespace shape."""
    if not isinstance(config, Mapping):
        raise TypeError("Configuration root must be a mapping.")

    converted = to_namespace(dict(config), cfg=_CONFIG_NAMESPACE_CONVERSION)
    if not isinstance(converted, SimpleNamespace):
        raise TypeError("Configuration namespace conversion failed.")
    return converted


def _platform_section_dict(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
) -> dict[str, Any]:
    root = _plain_data(config)
    if not isinstance(root, Mapping):
        return {}
    section = root.get(platform)
    if not isinstance(section, Mapping):
        return {}
    return copy.deepcopy(dict(section))


def _merged_platform_profile_dicts(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
) -> list[dict[str, Any]]:
    section = _platform_section_dict(config, platform=platform)
    if not section:
        return []

    profiles = section.get("profiles")
    base = {key: value for key, value in section.items() if key != "profiles"}
    if isinstance(profiles, list) and profiles:
        merged_profiles: list[dict[str, Any]] = []
        for index, item in enumerate(profiles):
            if not isinstance(item, Mapping):
                raise RuntimeError(
                    "Invalid configuration: "
                    f"{platform}.profiles[{index}] must be a table."
                )
            profile_key = _normalize_required_text(
                item.get("key"),
                field_name=f"{platform}.profiles[{index}].key",
            )
            overlay = {key: value for key, value in item.items() if key != "key"}
            merged = _deep_merge(base, overlay)
            merged["key"] = profile_key
            merged["runtime_profile_key"] = profile_key
            merged_profiles.append(merged)
        return merged_profiles

    legacy = copy.deepcopy(base)
    legacy["key"] = DEFAULT_RUNTIME_PROFILE_KEY
    legacy["runtime_profile_key"] = DEFAULT_RUNTIME_PROFILE_KEY
    return [legacy]


def get_platform_profile_sections(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
) -> tuple[SimpleNamespace, ...]:
    """Return merged per-profile platform sections with legacy normalization."""
    sections: list[SimpleNamespace] = []
    for section_dict in _merged_platform_profile_dicts(config, platform=platform):
        converted = to_namespace(section_dict, cfg=_CONFIG_NAMESPACE_CONVERSION)
        if not isinstance(converted, SimpleNamespace):
            raise TypeError("Platform profile namespace conversion failed.")
        sections.append(converted)
    return tuple(sections)


def get_platform_profile_dicts(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
) -> tuple[dict[str, Any], ...]:
    """Return merged per-profile platform config dictionaries."""
    return tuple(
        copy.deepcopy(section_dict)
        for section_dict in _merged_platform_profile_dicts(config, platform=platform)
    )


def get_platform_profile_section(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
    runtime_profile_key: str,
) -> SimpleNamespace:
    """Resolve one merged platform profile section by key."""
    requested_key = _normalize_required_text(
        runtime_profile_key,
        field_name=f"{platform}.runtime_profile_key",
    )
    for profile in get_platform_profile_sections(config, platform=platform):
        current_key = _normalize_optional_text(getattr(profile, "key", None))
        if current_key == requested_key:
            return profile
    raise KeyError(f"Unknown runtime profile key for {platform}: {requested_key!r}")


def get_platform_runtime_profile_keys(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
) -> tuple[str, ...]:
    """List configured runtime profile keys for one platform."""
    keys: list[str] = []
    for profile in get_platform_profile_sections(config, platform=platform):
        key = _normalize_optional_text(getattr(profile, "key", None))
        if key is not None:
            keys.append(key)
    return tuple(keys)


def normalize_runtime_profile_key(value: object) -> str | None:
    """Normalize one runtime profile key string."""
    return _normalize_optional_text(value)


def runtime_profile_key_from_ingress_route(
    ingress_route: Mapping[str, Any] | None,
) -> str | None:
    """Resolve runtime profile key from an ingress-route envelope."""
    if not isinstance(ingress_route, Mapping):
        return None
    return normalize_runtime_profile_key(ingress_route.get("runtime_profile_key"))


def get_active_runtime_profile_key() -> str | None:
    """Resolve the task-local active runtime profile key."""
    return normalize_runtime_profile_key(_ACTIVE_RUNTIME_PROFILE_KEY.get())


@contextlib.contextmanager
def runtime_profile_scope(runtime_profile_key: str | None):
    """Temporarily bind one active runtime profile key to the current task."""
    token = _ACTIVE_RUNTIME_PROFILE_KEY.set(
        normalize_runtime_profile_key(runtime_profile_key)
    )
    try:
        yield
    finally:
        _ACTIVE_RUNTIME_PROFILE_KEY.reset(token)


def clone_config_with_platform_profile(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
    runtime_profile_key: str,
) -> SimpleNamespace:
    """Clone full config and replace one platform section with one merged profile."""
    root = _plain_data(config)
    if not isinstance(root, Mapping):
        raise TypeError("Configuration root must be a mapping.")

    merged_section = _plain_data(
        get_platform_profile_section(
            config,
            platform=platform,
            runtime_profile_key=runtime_profile_key,
        )
    )
    if not isinstance(merged_section, Mapping):
        raise TypeError("Merged platform section must be a mapping.")

    cloned = copy.deepcopy(dict(root))
    cloned[platform] = dict(merged_section)
    return build_config_namespace(cloned)


def _nested_value(
    payload: Mapping[str, Any] | SimpleNamespace,
    path: tuple[str, ...],
) -> Any:
    current: Any = payload
    for part in path:
        if isinstance(current, Mapping):
            current = current.get(part)
            continue
        current = getattr(current, part, None)
    return current


def find_platform_runtime_profile_key(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
    identifier_type: str,
    identifier_value: str | None,
    filters: Mapping[str, str] | None = None,
) -> str | None:
    """Find a configured runtime profile key by one platform identifier."""
    normalized_identifier_type = _normalize_optional_text(identifier_type)
    normalized_identifier_value = _normalize_optional_text(identifier_value)
    if normalized_identifier_type is None or normalized_identifier_value is None:
        return None

    lookup_paths = _PLATFORM_IDENTIFIER_PATHS.get(platform, {})
    path = lookup_paths.get(normalized_identifier_type)
    if path is None:
        return None

    normalized_filters = {
        key: value
        for key, value in (
            (
                _normalize_optional_text(raw_key),
                _normalize_optional_text(raw_value),
            )
            for raw_key, raw_value in (filters or {}).items()
        )
        if key is not None and value is not None
    }

    for profile in get_platform_profile_sections(config, platform=platform):
        candidate_value = _normalize_optional_text(_nested_value(profile, path))
        if candidate_value != normalized_identifier_value:
            continue

        filter_mismatch = False
        for filter_key, filter_value in normalized_filters.items():
            filter_path = lookup_paths.get(filter_key)
            if filter_path is None:
                filter_mismatch = True
                break
            candidate_filter = _normalize_optional_text(
                _nested_value(profile, filter_path)
            )
            if candidate_filter != filter_value:
                filter_mismatch = True
                break
        if filter_mismatch:
            continue

        return _normalize_optional_text(getattr(profile, "key", None))

    return None


def identifier_configured_for_platform(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
    identifier_type: str,
) -> bool:
    """Check whether any configured profile exposes one identifier value."""
    normalized_identifier_type = _normalize_optional_text(identifier_type)
    if normalized_identifier_type is None:
        return False

    lookup_paths = _PLATFORM_IDENTIFIER_PATHS.get(platform, {})
    path = lookup_paths.get(normalized_identifier_type)
    if path is None:
        return False

    for profile in get_platform_profile_sections(config, platform=platform):
        if _normalize_optional_text(_nested_value(profile, path)) is not None:
            return True

    return False
