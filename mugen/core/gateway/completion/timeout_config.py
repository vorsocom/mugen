"""Shared timeout parsing helpers for completion gateways."""

from __future__ import annotations

from math import ceil
from math import isfinite
from types import SimpleNamespace
from typing import Any

from mugen.core.contract.gateway.logging import ILoggingGateway


def resolve_optional_positive_float(
    *,
    value: Any,
    field_name: str,
    provider_label: str,
    logging_gateway: ILoggingGateway,
) -> float | None:
    """Parse optional positive finite float."""
    _ = logging_gateway
    if value in [None, ""]:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid configuration: {provider_label}.{field_name} must be a positive "
            "finite number."
        ) from exc
    if isfinite(parsed) is not True:
        raise RuntimeError(
            f"Invalid configuration: {provider_label}.{field_name} must be a positive "
            "finite number."
        )
    if parsed <= 0:
        raise RuntimeError(
            f"Invalid configuration: {provider_label}.{field_name} must be greater than 0."
        )
    return parsed


def resolve_optional_positive_int(
    *,
    value: Any,
    field_name: str,
    provider_label: str,
    logging_gateway: ILoggingGateway,
) -> int | None:
    """Parse optional positive integer."""
    _ = logging_gateway
    if value in [None, ""]:
        return None
    if isinstance(value, bool):
        raise RuntimeError(
            f"Invalid configuration: {provider_label}.{field_name} must be a positive integer."
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid configuration: {provider_label}.{field_name} must be a positive integer."
        ) from exc
    if parsed <= 0:
        raise RuntimeError(
            f"Invalid configuration: {provider_label}.{field_name} must be greater than 0."
        )
    return parsed


def warn_missing_in_production(
    *,
    config: SimpleNamespace,
    provider_label: str,
    logging_gateway: ILoggingGateway,
    field_values: dict[str, Any],
) -> None:
    """Emit production warnings for missing timeout/retry controls."""
    environment = str(
        getattr(getattr(config, "mugen", SimpleNamespace()), "environment", "")
    ).strip().lower()
    if environment != "production":
        return

    for field_name, value in field_values.items():
        if value is not None:
            continue
        logging_gateway.warning(
            f"{provider_label}: {field_name} is not configured in production."
        )


def require_fields_in_production(
    *,
    config: SimpleNamespace,
    provider_label: str,
    field_values: dict[str, Any],
) -> None:
    """Fail fast in production when required controls are missing/invalid."""
    environment = str(
        getattr(getattr(config, "mugen", SimpleNamespace()), "environment", "")
    ).strip().lower()
    if environment != "production":
        return

    missing = sorted(
        field_name
        for field_name, value in field_values.items()
        if value is None
    )
    if not missing:
        return

    raise RuntimeError(
        f"{provider_label}: Missing required production configuration field(s): "
        f"{', '.join(missing)}."
    )


def to_timeout_milliseconds(seconds: float | None) -> int | None:
    """Convert timeout seconds to milliseconds without collapsing sub-second values."""
    if seconds is None:
        return None
    parsed = float(seconds)
    if isfinite(parsed) is not True or parsed <= 0:
        raise RuntimeError(
            "Invalid configuration: completion timeout must be a positive finite number."
        )
    return max(1, int(ceil(parsed * 1000.0)))


def parse_bool_like(
    *,
    value: Any,
    field_name: str,
    provider_label: str,
) -> bool:
    """Parse strict boolean-like values used in provider/vendor params."""
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
        raise ValueError(
            f"{provider_label}: Invalid boolean value for {field_name}. "
            "Use true/false (or on/off, yes/no, 1/0)."
        )

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(
            f"{provider_label}: Invalid boolean value for {field_name}. "
            "Use true/false (or on/off, yes/no, 1/0)."
        )

    raise ValueError(
        f"{provider_label}: Invalid boolean value for {field_name}. "
        "Use true/false (or on/off, yes/no, 1/0)."
    )
