"""Pure use-case logic for phase-B runtime health evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping

PHASE_STATUS_STARTING = "starting"
PHASE_STATUS_HEALTHY = "healthy"
PHASE_STATUS_DEGRADED = "degraded"
PHASE_STATUS_STOPPED = "stopped"


@dataclass(slots=True, frozen=True)
class PhaseBHealthInput:
    """Input contract for phase-B health evaluation."""

    platform_statuses: Mapping[str, Any]
    platform_errors: Mapping[str, Any]
    critical_platforms: list[str]
    degrade_on_critical_exit: bool
    shutdown_requested: bool
    phase_b_status: str
    phase_b_error: Any
    phase_b_started_at: object
    readiness_grace_seconds: float
    include_starting_failures: bool = False
    now_monotonic: float | None = None


@dataclass(slots=True, frozen=True)
class PhaseBHealthResult:
    """Output contract for phase-B health evaluation."""

    phase_b_status: str
    phase_b_error: str | None
    failed_critical_platforms: list[str]
    reasons: dict[str, str]
    ignore_starting: bool


def evaluate_phase_b_health(phase: PhaseBHealthInput) -> PhaseBHealthResult:
    """Evaluate aggregate phase-B status and critical-platform failures."""
    platform_statuses = _normalize_platform_statuses(phase.platform_statuses)
    platform_errors = _normalize_platform_errors(phase.platform_errors)
    critical_platforms = _normalize_platform_list(phase.critical_platforms)

    reported_status = _normalize_status(phase.phase_b_status)
    ignore_starting = _phase_b_starting_within_grace(
        phase_b_status=reported_status,
        phase_b_started_at=phase.phase_b_started_at,
        readiness_grace_seconds=phase.readiness_grace_seconds,
        now_monotonic=phase.now_monotonic,
    )

    if phase.shutdown_requested:
        return PhaseBHealthResult(
            phase_b_status=PHASE_STATUS_STOPPED,
            phase_b_error=None,
            failed_critical_platforms=[],
            reasons={},
            ignore_starting=False,
        )

    reported_error = _string_or_none(phase.phase_b_error)
    if reported_status == PHASE_STATUS_DEGRADED or reported_error is not None:
        failed_platforms, reasons = _resolve_failed_platforms(
            critical_platforms=critical_platforms,
            platform_statuses=platform_statuses,
            platform_errors=platform_errors,
            include_starting_failures=phase.include_starting_failures,
            ignore_starting=ignore_starting,
            degrade_on_critical_exit=phase.degrade_on_critical_exit,
        )
        aggregate_error = reported_error
        if aggregate_error is None:
            if failed_platforms:
                failed_platform = failed_platforms[0]
                aggregate_error = _default_platform_reason(
                    platform=failed_platform,
                    status=platform_statuses.get(failed_platform, ""),
                    platform_errors=platform_errors,
                )
            else:
                aggregate_error = "phase_b reported degraded"
        if not failed_platforms:
            reasons["phase_b"] = aggregate_error
        return PhaseBHealthResult(
            phase_b_status=PHASE_STATUS_DEGRADED,
            phase_b_error=aggregate_error,
            failed_critical_platforms=failed_platforms,
            reasons=reasons,
            ignore_starting=ignore_starting,
        )

    degraded: list[str] = []
    starting: list[str] = []
    unexpected: list[str] = []
    for platform in critical_platforms:
        status = platform_statuses.get(platform, PHASE_STATUS_STARTING)
        if status == PHASE_STATUS_DEGRADED:
            degraded.append(platform)
            continue
        if status == PHASE_STATUS_STARTING:
            starting.append(platform)
            continue
        if status == PHASE_STATUS_STOPPED and phase.degrade_on_critical_exit is not True:
            continue
        if status != PHASE_STATUS_HEALTHY:
            unexpected.append(platform)

    aggregate_status = PHASE_STATUS_HEALTHY
    aggregate_error: str | None = None
    if degraded:
        failed_platform = degraded[0]
        aggregate_status = PHASE_STATUS_DEGRADED
        aggregate_error = _default_platform_reason(
            platform=failed_platform,
            status=PHASE_STATUS_DEGRADED,
            platform_errors=platform_errors,
        )
    elif unexpected:
        failed_platform = unexpected[0]
        aggregate_status = PHASE_STATUS_DEGRADED
        aggregate_error = _default_platform_reason(
            platform=failed_platform,
            status=platform_statuses.get(failed_platform, ""),
            platform_errors=platform_errors,
        )
    elif starting:
        aggregate_status = PHASE_STATUS_STARTING

    failed_platforms, reasons = _resolve_failed_platforms(
        critical_platforms=critical_platforms,
        platform_statuses=platform_statuses,
        platform_errors=platform_errors,
        include_starting_failures=phase.include_starting_failures,
        ignore_starting=ignore_starting,
        degrade_on_critical_exit=phase.degrade_on_critical_exit,
    )
    return PhaseBHealthResult(
        phase_b_status=aggregate_status,
        phase_b_error=aggregate_error,
        failed_critical_platforms=failed_platforms,
        reasons=reasons,
        ignore_starting=ignore_starting,
    )


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status == "":
        return PHASE_STATUS_STARTING
    return status


def _normalize_platform_name(value: Any) -> str | None:
    normalized = str(value).strip().lower()
    if normalized == "":
        return None
    return normalized


def _normalize_platform_list(values: object) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    normalized: list[str] = []
    for item in values:
        platform = _normalize_platform_name(item)
        if platform is None or platform in normalized:
            continue
        normalized.append(platform)
    return normalized


def _normalize_platform_statuses(values: object) -> dict[str, str]:
    if not isinstance(values, Mapping):
        return {}
    normalized: dict[str, str] = {}
    for platform, status in values.items():
        normalized_platform = _normalize_platform_name(platform)
        if normalized_platform is None:
            continue
        normalized[normalized_platform] = _normalize_status(status)
    return normalized


def _normalize_platform_errors(values: object) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    normalized: dict[str, Any] = {}
    for platform, error in values.items():
        normalized_platform = _normalize_platform_name(platform)
        if normalized_platform is None:
            continue
        normalized[normalized_platform] = error
    return normalized


def _parse_nonnegative_float(value: object, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def _phase_b_starting_within_grace(
    *,
    phase_b_status: str,
    phase_b_started_at: object,
    readiness_grace_seconds: float,
    now_monotonic: float | None,
) -> bool:
    if phase_b_status != PHASE_STATUS_STARTING:
        return False
    grace_seconds = _parse_nonnegative_float(readiness_grace_seconds, default=0.0)
    if grace_seconds <= 0:
        return False
    try:
        started_at = float(phase_b_started_at)
    except (TypeError, ValueError):
        return False
    now = perf_counter() if now_monotonic is None else float(now_monotonic)
    return (now - started_at) < grace_seconds


def _default_platform_reason(
    *,
    platform: str,
    status: str,
    platform_errors: Mapping[str, Any],
) -> str:
    explicit_reason = _string_or_none(platform_errors.get(platform))
    if explicit_reason is not None:
        return f"{platform}: {explicit_reason}"
    normalized_status = _normalize_status(status)
    if normalized_status == PHASE_STATUS_STARTING:
        return f"{platform}: platform still starting"
    if normalized_status == PHASE_STATUS_STOPPED:
        return f"{platform}: stopped unexpectedly"
    if normalized_status == PHASE_STATUS_DEGRADED:
        return f"{platform}: degraded"
    return f"{platform}: platform status={normalized_status}"


def _resolve_failed_platforms(
    *,
    critical_platforms: list[str],
    platform_statuses: Mapping[str, str],
    platform_errors: Mapping[str, Any],
    include_starting_failures: bool,
    ignore_starting: bool,
    degrade_on_critical_exit: bool,
) -> tuple[list[str], dict[str, str]]:
    failed: list[str] = []
    reasons: dict[str, str] = {}
    for platform in critical_platforms:
        status = _normalize_status(platform_statuses.get(platform, PHASE_STATUS_STARTING))
        if status == PHASE_STATUS_HEALTHY:
            continue
        if status == PHASE_STATUS_STARTING:
            if ignore_starting or include_starting_failures is not True:
                continue
        elif status == PHASE_STATUS_STOPPED and degrade_on_critical_exit is not True:
            continue

        failed.append(platform)
        reason = _string_or_none(platform_errors.get(platform))
        if reason is None:
            if status == PHASE_STATUS_STARTING:
                reason = "platform still starting"
            elif status == PHASE_STATUS_STOPPED:
                reason = "platform stopped"
            elif status == PHASE_STATUS_DEGRADED:
                reason = "platform degraded"
            else:
                reason = f"platform status={status}"
        reasons[platform] = reason
    return failed, reasons


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return text
