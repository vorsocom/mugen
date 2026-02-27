"""Helpers for canonical core platform normalization and validation."""

from __future__ import annotations

SUPPORTED_CORE_PLATFORMS = frozenset(
    {
        "matrix",
        "telnet",
        "web",
        "whatsapp",
    }
)


def normalize_platforms(values: object) -> list[str]:
    """Normalize platform names to lower-case unique values."""
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []

    normalized: list[str] = []
    for item in values:
        platform = str(item).strip().lower()
        if platform == "":
            continue
        if platform in normalized:
            continue
        normalized.append(platform)
    return normalized


def unknown_platforms(values: object) -> list[str]:
    """Return normalized platform values not in the supported allow-list."""
    normalized = normalize_platforms(values)
    return [
        platform
        for platform in normalized
        if platform not in SUPPORTED_CORE_PLATFORMS
    ]
