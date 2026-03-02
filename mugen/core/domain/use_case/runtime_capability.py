"""Pure use-case logic for phase-A runtime capability validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

PHASE_STATUS_HEALTHY = "healthy"
PHASE_STATUS_DEGRADED = "degraded"

_MESSAGING_PLATFORMS = {"matrix", "web", "whatsapp"}


@dataclass(slots=True, frozen=True)
class RuntimeCapabilityInput:
    """Input contract for runtime capability evaluation."""

    active_platforms: list[str]
    messaging_handler_platforms: list[object]
    has_web_fw_extension: bool
    has_web_client_runtime_path: bool
    container_ready: bool = True
    provider_ready: bool = True


@dataclass(slots=True, frozen=True)
class RuntimeCapabilityResult:
    """Output contract for runtime capability evaluation."""

    statuses: dict[str, str]
    errors: dict[str, str | None]
    failed_capabilities: list[str]
    healthy: bool


def evaluate_runtime_capabilities(
    capability: RuntimeCapabilityInput,
) -> RuntimeCapabilityResult:
    """Evaluate runtime capabilities required for phase-A bootstrap."""
    active_platforms = _normalize_platforms(capability.active_platforms)
    handler_scopes = _normalize_handler_scopes(capability.messaging_handler_platforms)

    statuses: dict[str, str] = {}
    errors: dict[str, str | None] = {}
    failed_capabilities: list[str] = []

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

    for platform in active_platforms:
        if platform not in _MESSAGING_PLATFORMS:
            continue
        _record(
            f"messaging.mh.{platform}",
            healthy=_platform_has_handler(platform=platform, handler_scopes=handler_scopes),
            error=(
                "Missing message handler capability for active platform "
                f"'{platform}'."
            ),
        )

    if "web" in active_platforms:
        _record(
            "web.fw_extension",
            healthy=capability.has_web_fw_extension,
            error=(
                "Web platform requires enabled framework extension token "
                "'core.fw.web'."
            ),
        )
        _record(
            "web.client_runtime_path",
            healthy=capability.has_web_client_runtime_path,
            error=(
                "Web platform requires configured runtime client path at "
                "mugen.modules.core.client.web."
            ),
        )

    return RuntimeCapabilityResult(
        statuses=statuses,
        errors=errors,
        failed_capabilities=failed_capabilities,
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
