"""Pure use-case logic for web stream cursor continuity."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class WebStreamContinuityInput:
    """Input contract for stream continuity decisions."""

    expected_stream_generation: str | None
    observed_stream_generation: str | None
    requested_after_event_id: int
    effective_after_event_id: int
    first_event_id: int | None
    generation_changed_reason: str
    cursor_gap_reason: str


@dataclass(slots=True, frozen=True)
class WebStreamContinuityResult:
    """Output contract for stream continuity decisions."""

    reset_required: bool
    reset_reason: str | None
    expected_next_event_id: int


def evaluate_web_stream_continuity(
    continuity: WebStreamContinuityInput,
) -> WebStreamContinuityResult:
    """Evaluate whether stream cursor continuity requires an explicit reset."""
    expected_generation = _normalize_generation(continuity.expected_stream_generation)
    observed_generation = _normalize_generation(continuity.observed_stream_generation)
    if (
        expected_generation is not None
        and observed_generation is not None
        and expected_generation != observed_generation
    ):
        return WebStreamContinuityResult(
            reset_required=True,
            reset_reason=_normalize_reason(
                continuity.generation_changed_reason,
                fallback="generation_changed",
            ),
            expected_next_event_id=1,
        )

    effective_after_event_id = _coerce_nonnegative_int(
        continuity.effective_after_event_id,
        default=0,
    )
    expected_next_event_id = effective_after_event_id + 1
    first_event_id = _coerce_positive_int_or_none(continuity.first_event_id)
    if first_event_id is not None and first_event_id > expected_next_event_id:
        return WebStreamContinuityResult(
            reset_required=True,
            reset_reason=_normalize_reason(
                continuity.cursor_gap_reason,
                fallback="cursor_gap",
            ),
            expected_next_event_id=expected_next_event_id,
        )

    return WebStreamContinuityResult(
        reset_required=False,
        reset_reason=None,
        expected_next_event_id=expected_next_event_id,
    )


def _normalize_generation(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized == "":
        return None
    return normalized


def _normalize_reason(value: str, *, fallback: str) -> str:
    normalized = str(value).strip()
    if normalized == "":
        return fallback
    return normalized


def _coerce_nonnegative_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def _coerce_positive_int_or_none(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed
