"""Canonical runtime bootstrap contract parsing for startup and DI."""

from __future__ import annotations

from dataclasses import dataclass

from mugen.core.utility.config_value import (
    parse_bool_flag,
    parse_nonnegative_finite_float,
    parse_required_positive_finite_float,
)
from mugen.core.utility.platforms import normalize_platforms

__all__ = [
    "RuntimeBootstrapSettings",
    "parse_runtime_bootstrap_settings",
]

_PROFILE_KEY = "mugen.runtime.profile"
_READINESS_GRACE_KEY = "mugen.runtime.phase_b.readiness_grace_seconds"
_STARTUP_TIMEOUT_KEY = "mugen.runtime.phase_b.startup_timeout_seconds"
_PROVIDER_TIMEOUT_KEY = "mugen.runtime.provider_readiness_timeout_seconds"
_PROVIDER_SHUTDOWN_TIMEOUT_KEY = "mugen.runtime.provider_shutdown_timeout_seconds"
_SHUTDOWN_TIMEOUT_KEY = "mugen.runtime.shutdown_timeout_seconds"
_ALLOWED_PROFILES = {"platform_full"}


@dataclass(slots=True, frozen=True)
class RuntimeBootstrapSettings:
    """Parsed runtime bootstrap controls used across startup workflows."""

    raw_platforms: object
    active_platforms: list[str]
    critical_platforms: list[str]
    degrade_on_critical_exit: bool
    readiness_grace_seconds: float
    profile: str
    startup_timeout_seconds: float
    provider_readiness_timeout_seconds: float
    provider_shutdown_timeout_seconds: float
    shutdown_timeout_seconds: float


_MISSING = object()


def _read_path(config: object, *path: str) -> object:
    current: object = config
    for key in path:
        if isinstance(current, dict):
            if key not in current:
                return _MISSING
            current = current[key]
            continue
        if current is None:
            return _MISSING
        current_dict = getattr(current, "__dict__", None)
        if (
            isinstance(current_dict, dict)
            and key not in current_dict
            and hasattr(type(current), key) is not True
        ):
            return _MISSING
        if hasattr(current, key) is not True:
            return _MISSING
        current = getattr(current, key)
    return current


def _parse_runtime_profile(raw_value: object) -> str:
    if raw_value is _MISSING:
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            f"{_PROFILE_KEY} is required and must be platform_full."
        )
    if not isinstance(raw_value, str):
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            f"{_PROFILE_KEY} must be a string."
        )
    normalized = raw_value.strip().lower()
    if normalized in {"", "auto"}:
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            f"{_PROFILE_KEY} must be explicitly set to platform_full."
        )
    if normalized not in _ALLOWED_PROFILES:
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            f"{_PROFILE_KEY} must be platform_full."
        )
    return normalized


def parse_runtime_bootstrap_settings(config: object) -> RuntimeBootstrapSettings:
    """Parse canonical runtime bootstrap controls from dict or namespace config."""
    raw_platforms = _read_path(config, "mugen", "platforms")
    normalized_active = normalize_platforms(
        raw_platforms if isinstance(raw_platforms, list) else []
    )

    raw_critical = _read_path(config, "mugen", "runtime", "phase_b", "critical_platforms")
    critical_platforms = normalize_platforms(raw_critical)
    if not critical_platforms:
        critical_platforms = list(normalized_active)

    raw_degrade = _read_path(
        config,
        "mugen",
        "runtime",
        "phase_b",
        "degrade_on_critical_exit",
    )
    degrade_on_critical_exit = parse_bool_flag(
        True if raw_degrade is _MISSING else raw_degrade,
        default=True,
    )

    raw_grace = _read_path(
        config,
        "mugen",
        "runtime",
        "phase_b",
        "readiness_grace_seconds",
    )
    readiness_grace_seconds = parse_nonnegative_finite_float(
        None if raw_grace is _MISSING else raw_grace,
        field_name=_READINESS_GRACE_KEY,
        default=0.0,
    )

    profile = _parse_runtime_profile(
        _read_path(config, "mugen", "runtime", "profile")
    )

    raw_startup_timeout = _read_path(
        config,
        "mugen",
        "runtime",
        "phase_b",
        "startup_timeout_seconds",
    )
    startup_timeout_seconds = parse_required_positive_finite_float(
        None if raw_startup_timeout is _MISSING else raw_startup_timeout,
        _STARTUP_TIMEOUT_KEY,
    )

    raw_provider_timeout = _read_path(
        config,
        "mugen",
        "runtime",
        "provider_readiness_timeout_seconds",
    )
    provider_readiness_timeout_seconds = parse_required_positive_finite_float(
        None if raw_provider_timeout is _MISSING else raw_provider_timeout,
        _PROVIDER_TIMEOUT_KEY,
    )

    raw_provider_shutdown_timeout = _read_path(
        config,
        "mugen",
        "runtime",
        "provider_shutdown_timeout_seconds",
    )
    provider_shutdown_timeout_seconds = parse_required_positive_finite_float(
        None if raw_provider_shutdown_timeout is _MISSING else raw_provider_shutdown_timeout,
        _PROVIDER_SHUTDOWN_TIMEOUT_KEY,
    )

    raw_shutdown_timeout = _read_path(
        config,
        "mugen",
        "runtime",
        "shutdown_timeout_seconds",
    )
    shutdown_timeout_seconds = parse_required_positive_finite_float(
        None if raw_shutdown_timeout is _MISSING else raw_shutdown_timeout,
        _SHUTDOWN_TIMEOUT_KEY,
    )

    if raw_platforms is _MISSING:
        raw_platforms = None

    return RuntimeBootstrapSettings(
        raw_platforms=raw_platforms,
        active_platforms=normalized_active,
        critical_platforms=critical_platforms,
        degrade_on_critical_exit=degrade_on_critical_exit,
        readiness_grace_seconds=readiness_grace_seconds,
        profile=profile,
        startup_timeout_seconds=startup_timeout_seconds,
        provider_readiness_timeout_seconds=provider_readiness_timeout_seconds,
        provider_shutdown_timeout_seconds=provider_shutdown_timeout_seconds,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
    )
