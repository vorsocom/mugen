"""Shared sampling-control helpers for completion gateways."""

from __future__ import annotations

from typing import Any

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionRequest,
)

SAMPLING_CONTROLS_CONFIG_KEY = "sampling_controls"
SAMPLING_CONTROLS_ENABLED = "enabled"
SAMPLING_CONTROLS_DISABLED = "disabled"


def resolve_sampling_controls_enabled(
    *,
    request: CompletionRequest,
    operation_config: dict[str, Any],
    provider: str,
    provider_label: str,
    timeout_applied: float | None = None,
) -> bool:
    """Resolve whether temperature/top_p should be serialized."""
    raw_value = operation_config.get(
        SAMPLING_CONTROLS_CONFIG_KEY,
        SAMPLING_CONTROLS_ENABLED,
    )
    if raw_value is None or raw_value == "":
        return True
    if not isinstance(raw_value, str):
        raise CompletionGatewayError(
            provider=provider,
            operation=request.operation,
            message=(
                f"{provider_label}: Invalid sampling_controls value. "
                "Expected 'enabled' or 'disabled'."
            ),
            timeout_applied=timeout_applied,
        )

    normalized_value = raw_value.strip().lower().replace("-", "_")
    if normalized_value == SAMPLING_CONTROLS_ENABLED:
        return True
    if normalized_value == SAMPLING_CONTROLS_DISABLED:
        return False

    raise CompletionGatewayError(
        provider=provider,
        operation=request.operation,
        message=(
            f"{provider_label}: Invalid sampling_controls value. "
            "Expected 'enabled' or 'disabled'."
        ),
        timeout_applied=timeout_applied,
    )


def resolve_sampling_parameter_kwargs(
    *,
    request: CompletionRequest,
    operation_config: dict[str, Any],
    provider: str,
    provider_label: str,
    timeout_applied: float | None = None,
    temperature_key: str = "temperature",
    top_p_key: str = "top_p",
    config_temperature_key: str | None = "temp",
    config_top_p_key: str | None = "top_p",
    default_temperature: float | None = None,
    default_top_p: float | None = None,
) -> dict[str, float]:
    """Build provider kwargs for normalized temperature/top_p controls."""
    sampling_controls_enabled = resolve_sampling_controls_enabled(
        request=request,
        operation_config=operation_config,
        provider=provider,
        provider_label=provider_label,
        timeout_applied=timeout_applied,
    )
    if sampling_controls_enabled is not True:
        return {}

    sampling_kwargs: dict[str, float] = {}

    temperature = _resolve_sampling_value(
        request_value=request.inference.temperature,
        operation_config=operation_config,
        config_key=config_temperature_key,
        default_value=default_temperature,
    )
    if temperature is not None:
        sampling_kwargs[temperature_key] = temperature

    top_p = _resolve_sampling_value(
        request_value=request.inference.top_p,
        operation_config=operation_config,
        config_key=config_top_p_key,
        default_value=default_top_p,
    )
    if top_p is not None:
        sampling_kwargs[top_p_key] = top_p

    return sampling_kwargs


def _resolve_sampling_value(
    *,
    request_value: float | None,
    operation_config: dict[str, Any],
    config_key: str | None,
    default_value: float | None,
) -> float | None:
    if request_value is not None:
        return float(request_value)
    if config_key is not None and config_key in operation_config:
        return float(operation_config[config_key])
    if default_value is not None:
        return float(default_value)
    return None
