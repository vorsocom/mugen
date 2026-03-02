"""Canonical runtime bootstrap contract parsing for DI and phase-B startup."""

from __future__ import annotations

from dataclasses import dataclass

from mugen.core.utility.platforms import normalize_platforms

_PROFILE_KEY = "mugen.runtime.profile"
_STARTUP_TIMEOUT_KEY = "mugen.runtime.phase_b.startup_timeout_seconds"
_PROVIDER_TIMEOUT_KEY = "mugen.runtime.provider_readiness_timeout_seconds"
_ALLOWED_PROFILES = {"api_only", "web_only", "platform_full"}


@dataclass(slots=True, frozen=True)
class RuntimeBootstrapSettings:
    """Parsed runtime bootstrap controls used across startup workflows."""

    raw_platforms: object
    active_platforms: list[str]
    critical_platforms: list[str]
    degrade_on_critical_exit: bool
    readiness_grace_seconds: float
    profile: str | None
    startup_timeout_seconds: float | None
    provider_readiness_timeout_seconds: float | None


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
        if hasattr(current, key) is not True:
            return _MISSING
        current = getattr(current, key)
    return current


def _parse_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _parse_nonnegative_float(value: object, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def _parse_required_positive_float(
    *,
    raw_value: object,
    missing_message: str,
    invalid_message: str,
    nonpositive_message: str,
) -> float:
    if raw_value in {_MISSING, None, ""}:
        raise RuntimeError(missing_message)
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(invalid_message) from exc
    if parsed <= 0:
        raise RuntimeError(nonpositive_message)
    return parsed


def _parse_runtime_profile(raw_value: object) -> str:
    if raw_value is _MISSING:
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            "mugen.runtime.profile is required and must be one of "
            "api_only|web_only|platform_full."
        )
    if not isinstance(raw_value, str):
        raise RuntimeError(
            "Invalid runtime profile configuration: mugen.runtime.profile must be a string."
        )
    normalized = raw_value.strip().lower()
    if normalized in {"", "auto"}:
        raise RuntimeError(
            "Invalid runtime profile configuration: mugen.runtime.profile must be "
            "explicitly set to one of api_only|web_only|platform_full."
        )
    if normalized not in _ALLOWED_PROFILES:
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            "mugen.runtime.profile must be one of api_only|web_only|platform_full."
        )
    return normalized


def parse_runtime_bootstrap_settings(
    config: object,
    *,
    require_profile: bool,
    require_startup_timeout_seconds: bool,
    require_provider_readiness_timeout_seconds: bool,
) -> RuntimeBootstrapSettings:
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
    degrade_on_critical_exit = _parse_bool(
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
    readiness_grace_seconds = _parse_nonnegative_float(
        0.0 if raw_grace is _MISSING else raw_grace,
        default=0.0,
    )

    profile: str | None = None
    if require_profile:
        profile = _parse_runtime_profile(
            _read_path(config, "mugen", "runtime", "profile")
        )

    startup_timeout_seconds: float | None = None
    if require_startup_timeout_seconds:
        startup_timeout_seconds = _parse_required_positive_float(
            raw_value=_read_path(config, "mugen", "runtime", "phase_b", "startup_timeout_seconds"),
            missing_message=(
                "Invalid runtime configuration: "
                f"{_STARTUP_TIMEOUT_KEY} is required."
            ),
            invalid_message=(
                "Invalid runtime configuration: "
                f"{_STARTUP_TIMEOUT_KEY} must be a positive number."
            ),
            nonpositive_message=(
                "Invalid runtime configuration: "
                f"{_STARTUP_TIMEOUT_KEY} must be greater than 0."
            ),
        )

    provider_readiness_timeout_seconds: float | None = None
    if require_provider_readiness_timeout_seconds:
        provider_readiness_timeout_seconds = _parse_required_positive_float(
            raw_value=_read_path(
                config,
                "mugen",
                "runtime",
                "provider_readiness_timeout_seconds",
            ),
            missing_message=(
                "Invalid runtime configuration: "
                f"{_PROVIDER_TIMEOUT_KEY} is required."
            ),
            invalid_message=(
                "Invalid runtime configuration: "
                f"{_PROVIDER_TIMEOUT_KEY} must be a positive number."
            ),
            nonpositive_message=(
                "Invalid runtime configuration: "
                f"{_PROVIDER_TIMEOUT_KEY} must be greater than 0."
            ),
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
    )
