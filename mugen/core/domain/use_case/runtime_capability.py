"""Pure use-case logic for phase-A runtime capability validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

PHASE_STATUS_HEALTHY = "healthy"
PHASE_STATUS_DEGRADED = "degraded"

_MESSAGING_PLATFORMS = {"matrix", "web", "whatsapp"}
_REQUIRED_WEB_FW_EXTENSION_TOKENS = (
    "core.fw.acp",
    "core.fw.web",
)


@dataclass(slots=True, frozen=True)
class RuntimeCapabilityInput:
    """Input contract for runtime capability evaluation."""

    active_platforms: list[str]
    messaging_handler_platforms: list[object]
    mh_mode: str
    has_web_client_runtime_path: bool
    registered_fw_extension_tokens: list[object] | None = None
    container_ready: bool = True
    provider_ready: bool = True
    optional_provider_failures: dict[str, str] | None = None


@dataclass(slots=True, frozen=True)
class RuntimeCapabilityResult:
    """Output contract for runtime capability evaluation."""

    statuses: dict[str, str]
    errors: dict[str, str | None]
    failed_capabilities: list[str]
    non_blocking_degraded_capabilities: list[str]
    healthy: bool


def evaluate_runtime_capabilities(
    capability: RuntimeCapabilityInput,
) -> RuntimeCapabilityResult:
    """Evaluate runtime capabilities required for phase-A bootstrap."""
    active_platforms = _normalize_platforms(capability.active_platforms)
    handler_scopes = _normalize_handler_scopes(capability.messaging_handler_platforms)
    mh_mode = _normalize_mh_mode(capability.mh_mode)
    registered_fw_extension_tokens = _normalize_extension_tokens(
        capability.registered_fw_extension_tokens
    )

    statuses: dict[str, str] = {}
    errors: dict[str, str | None] = {}
    failed_capabilities: list[str] = []
    non_blocking_degraded_capabilities: list[str] = []

    def _record(name: str, *, healthy: bool, error: str) -> None:
        if healthy:
            statuses[name] = PHASE_STATUS_HEALTHY
            errors[name] = None
            return
        statuses[name] = PHASE_STATUS_DEGRADED
        errors[name] = error
        failed_capabilities.append(name)

    _record(
        "container_readiness",
        healthy=capability.container_ready,
        error="Container readiness check failed.",
    )
    _record(
        "provider_readiness",
        healthy=capability.provider_ready,
        error="Provider readiness check failed.",
    )

    optional_provider_failures = capability.optional_provider_failures
    if isinstance(optional_provider_failures, dict):
        for provider_name in sorted(optional_provider_failures.keys()):
            error_message = optional_provider_failures[provider_name]
            if not isinstance(error_message, str) or error_message.strip() == "":
                error_message = (
                    "Optional provider readiness check failed."
                )
            capability_name = f"provider_readiness.optional.{provider_name}"
            statuses[capability_name] = PHASE_STATUS_DEGRADED
            errors[capability_name] = error_message
            non_blocking_degraded_capabilities.append(capability_name)
    _record(
        "messaging.mh.mode",
        healthy=mh_mode is not None,
        error=(
            "Invalid messaging handler mode. "
            "mugen.messaging.mh_mode must be 'optional' or 'required'."
        ),
    )

    has_any_handler = _has_any_handler(handler_scopes)
    _record(
        "messaging.mh.availability",
        healthy=has_any_handler or mh_mode == "optional",
        error=(
            "No message handler extensions are bound while "
            "mugen.messaging.mh_mode='required'."
        ),
    )

    for platform in active_platforms:
        if platform not in _MESSAGING_PLATFORMS:
            continue
        platform_has_handler = _platform_has_handler(
            platform=platform,
            handler_scopes=handler_scopes,
        )
        if mh_mode == "required":
            platform_healthy = platform_has_handler
            error_message = (
                "Missing message handler capability for active platform "
                f"'{platform}' while mugen.messaging.mh_mode='required'."
            )
        elif mh_mode == "optional":
            platform_healthy = True
            error_message = (
                "Missing built-in messaging capability for active platform "
                f"'{platform}' while mugen.messaging.mh_mode='optional'."
            )
        else:
            platform_healthy = False
            error_message = (
                "Messaging handler mode is invalid; capability resolution "
                f"for active platform '{platform}' failed."
            )
        _record(
            f"messaging.mh.{platform}",
            healthy=platform_healthy,
            error=error_message,
        )

    if "web" in active_platforms:
        _record(
            "web.client_runtime_path",
            healthy=capability.has_web_client_runtime_path,
            error=(
                "Web platform requires configured runtime client path at "
                "mugen.modules.core.client.web."
            ),
        )
        missing_tokens = [
            token
            for token in _REQUIRED_WEB_FW_EXTENSION_TOKENS
            if token not in registered_fw_extension_tokens
        ]
        _record(
            "web.fw.extension_contract",
            healthy=not missing_tokens,
            error=(
                "Web platform requires registered FW extension token(s): "
                + ", ".join(missing_tokens)
                + "."
            ),
        )

    return RuntimeCapabilityResult(
        statuses=statuses,
        errors=errors,
        failed_capabilities=failed_capabilities,
        non_blocking_degraded_capabilities=non_blocking_degraded_capabilities,
        healthy=not failed_capabilities,
    )


def _normalize_platforms(values: object) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    normalized: list[str] = []
    for value in values:
        candidate = str(value or "").strip().lower()
        if candidate == "" or candidate in normalized:
            continue
        normalized.append(candidate)
    return normalized


def _normalize_handler_scopes(values: object) -> list[set[str] | None]:
    if not isinstance(values, list):
        return []
    scopes: list[set[str] | None] = []
    for value in values:
        if isinstance(value, (list, tuple, set, frozenset)):
            normalized = set(_normalize_platforms(list(value)))
            if not normalized:
                scopes.append(None)
                continue
            scopes.append(normalized)
            continue
        if value is None:
            scopes.append(None)
            continue
        scopes.append(set())
    return scopes


def _normalize_mh_mode(value: object) -> str | None:
    candidate = str(value or "").strip().lower()
    if candidate in {"optional", "required"}:
        return candidate
    return None


def _normalize_extension_tokens(values: object) -> set[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return set()
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        token = value.strip().lower()
        if token == "":
            continue
        normalized.add(token)
    return normalized


def _has_any_handler(handler_scopes: Iterable[set[str] | None]) -> bool:
    for scope in handler_scopes:
        if scope is None:
            return True
        if isinstance(scope, set) and scope:
            return True
    return False


def _platform_has_handler(
    *,
    platform: str,
    handler_scopes: Iterable[set[str] | None],
) -> bool:
    for scope in handler_scopes:
        if scope is None:
            return True
        if platform in scope:
            return True
    return False
