"""Security-focused configuration validation helpers."""

from __future__ import annotations

_DEFAULT_MIN_SECRET_KEY_LENGTH = 32
_COMMON_PLACEHOLDERS = frozenset(
    {
        "secret_key",
        "changeme",
        "change-me",
        "change_me",
        "default",
        "placeholder",
        "replace_me",
        "set-me",
        "set_me",
    }
)
_COMMON_PLACEHOLDER_SUBSTRINGS = (
    "changeme",
    "change-me",
    "change_me",
    "replace_me",
    "set-me",
    "set_me",
    "placeholder",
    "secret_key",
)


def validate_quart_secret_key(
    value: object,
    *,
    min_length: int = _DEFAULT_MIN_SECRET_KEY_LENGTH,
) -> str:
    """Validate Quart secret key quality for deployment-safe defaults."""
    if isinstance(value, str) is not True:
        raise RuntimeError(
            "Invalid configuration: quart.secret_key must be a string."
        )

    normalized = value.strip()
    if normalized == "":
        raise RuntimeError(
            "Invalid configuration: quart.secret_key must be non-empty."
        )

    if len(normalized) < min_length:
        raise RuntimeError(
            "Invalid configuration: quart.secret_key must contain at least "
            f"{min_length} characters."
        )

    lowered = normalized.lower()
    if lowered in _COMMON_PLACEHOLDERS or any(
        marker in lowered for marker in _COMMON_PLACEHOLDER_SUBSTRINGS
    ):
        raise RuntimeError(
            "Invalid configuration: quart.secret_key must not use placeholder values."
        )

    if (
        lowered.startswith("<set-")
        or lowered.startswith("<replace-")
        or (normalized.startswith("<") and normalized.endswith(">"))
    ):
        raise RuntimeError(
            "Invalid configuration: quart.secret_key must not use placeholder values."
        )

    return normalized
