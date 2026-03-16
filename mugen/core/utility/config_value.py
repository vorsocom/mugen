"""Strict configuration value parsing helpers."""

from __future__ import annotations

from math import isfinite


def parse_bool_flag(value: object, default: bool) -> bool:
    """Parse a boolean-like flag with fallback to ``default``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def parse_required_positive_finite_float(value: object, field_name: str) -> float:
    """Parse a required positive finite float."""
    if value is None or value == "":
        raise RuntimeError(f"Invalid configuration: {field_name} is required.")
    parsed = _parse_finite_float(value, field_name, positive=True)
    if parsed <= 0:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be greater than 0."
        )
    return parsed


def parse_optional_positive_finite_float(
    value: object,
    field_name: str,
) -> float | None:
    """Parse an optional positive finite float."""
    if value is None or value == "":
        return None
    parsed = _parse_finite_float(value, field_name, positive=True)
    if parsed <= 0:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be greater than 0."
        )
    return parsed


def parse_nonnegative_finite_float(
    value: object,
    field_name: str,
    default: float,
) -> float:
    """Parse a non-negative finite float with default for missing values."""
    if value is None or value == "":
        _ensure_default_nonnegative_finite(default, field_name)
        return float(default)
    parsed = _parse_finite_float(value, field_name, positive=False)
    if parsed < 0:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be greater than or equal to 0."
        )
    return parsed


def parse_required_positive_int(value: object, field_name: str) -> int:
    """Parse a required positive integer."""
    if value is None or value == "":
        raise RuntimeError(f"Invalid configuration: {field_name} is required.")
    parsed = _parse_int(value, field_name)
    if parsed <= 0:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be greater than 0."
        )
    return parsed


def parse_optional_positive_int(value: object, field_name: str) -> int | None:
    """Parse an optional positive integer."""
    if value is None or value == "":
        return None
    parsed = _parse_int(value, field_name)
    if parsed <= 0:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be greater than 0."
        )
    return parsed


def _parse_finite_float(value: object, field_name: str, *, positive: bool) -> float:
    qualifier = "positive finite number" if positive else "non-negative finite number"
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be a {qualifier}."
        ) from exc
    if isfinite(parsed) is not True:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be a {qualifier}."
        )
    return parsed


def _parse_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be a positive integer."
        )
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be a positive integer."
        ) from exc


def _ensure_default_nonnegative_finite(default: float, field_name: str) -> None:
    if isfinite(float(default)) is not True or float(default) < 0:
        raise RuntimeError(
            f"Invalid configuration: {field_name} default must be non-negative finite."
        )
