"""Shared phase-B runtime control parsing helpers."""

from __future__ import annotations

from mugen.core.runtime.bootstrap_contract import parse_runtime_bootstrap_settings
from mugen.core.utility.config_value import (
    parse_bool_flag,
    parse_nonnegative_finite_float,
)
from mugen.core.utility.platforms import normalize_platforms

_STARTUP_TIMEOUT_KEY = "mugen.runtime.phase_b.startup_timeout_seconds"


def parse_bool(value: object, *, default: bool) -> bool:
    """Parse common truthy/falsy values with a default fallback."""
    return parse_bool_flag(value, default)


def parse_nonnegative_float(value: object, *, default: float) -> float:
    """Parse non-negative float values with a default fallback."""
    try:
        return parse_nonnegative_finite_float(
            value,
            field_name="phase_b.nonnegative_float",
            default=default,
        )
    except RuntimeError:
        return default


def normalize_platform_list(values: object) -> list[str]:
    """Normalize platform names to lower-case unique values."""
    return normalize_platforms(values)


def resolve_phase_b_runtime_controls(config: object) -> tuple[float, list[str], bool]:
    """Resolve readiness grace, critical platforms, and degrade policy."""
    settings = parse_runtime_bootstrap_settings(
        config,
        require_profile=False,
        require_startup_timeout_seconds=False,
        require_provider_readiness_timeout_seconds=False,
    )
    return (
        settings.readiness_grace_seconds,
        list(settings.critical_platforms),
        settings.degrade_on_critical_exit,
    )


def resolve_phase_b_startup_timeout_seconds(config: object) -> float:
    """Resolve required phase-B startup timeout as a positive float."""
    settings = parse_runtime_bootstrap_settings(
        config,
        require_profile=False,
        require_startup_timeout_seconds=True,
        require_provider_readiness_timeout_seconds=False,
    )
    return float(settings.startup_timeout_seconds)


def resolve_phase_b_startup_failure_cancel_timeout_seconds(config: object) -> float:
    """Resolve bounded timeout used while cancelling phase-B startup on failure."""
    settings = parse_runtime_bootstrap_settings(
        config,
        require_profile=False,
        require_startup_timeout_seconds=False,
        require_provider_readiness_timeout_seconds=False,
        require_provider_shutdown_timeout_seconds=True,
    )
    return float(settings.provider_shutdown_timeout_seconds)
