"""Shared phase-B runtime control parsing helpers."""

from __future__ import annotations

from types import SimpleNamespace


def parse_bool(value: object, *, default: bool) -> bool:
    """Parse common truthy/falsy values with a default fallback."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def parse_nonnegative_float(value: object, *, default: float) -> float:
    """Parse non-negative float values with a default fallback."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def normalize_platform_list(values: object) -> list[str]:
    """Normalize platform names to lower-case unique values."""
    if not isinstance(values, list):
        return []

    normalized: list[str] = []
    for item in values:
        platform = str(item).strip().lower()
        if platform == "" or platform in normalized:
            continue
        normalized.append(platform)
    return normalized


def resolve_phase_b_runtime_controls(config: object) -> tuple[float, list[str], bool]:
    """Resolve readiness grace, critical platforms, and degrade policy."""
    mugen_cfg = getattr(config, "mugen", SimpleNamespace())
    runtime_cfg = getattr(mugen_cfg, "runtime", SimpleNamespace())
    phase_b_cfg = getattr(runtime_cfg, "phase_b", SimpleNamespace())

    readiness_grace = parse_nonnegative_float(
        getattr(phase_b_cfg, "readiness_grace_seconds", 0.0),
        default=0.0,
    )
    degrade_on_critical_exit = parse_bool(
        getattr(phase_b_cfg, "degrade_on_critical_exit", True),
        default=True,
    )

    critical_platforms = normalize_platform_list(
        getattr(phase_b_cfg, "critical_platforms", None)
    )
    if critical_platforms:
        return readiness_grace, critical_platforms, degrade_on_critical_exit

    active_platforms = normalize_platform_list(getattr(mugen_cfg, "platforms", []))
    return readiness_grace, active_platforms, degrade_on_critical_exit
