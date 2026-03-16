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


def _validate_secret_value(
    value: object,
    *,
    path: str,
    min_length: int,
) -> str:
    """Validate secret-like string values with placeholder rejection."""
    if isinstance(value, str) is not True:
        raise RuntimeError(
            f"Invalid configuration: {path} must be a string."
        )

    normalized = value.strip()
    if normalized == "":
        raise RuntimeError(
            f"Invalid configuration: {path} must be non-empty."
        )

    lowered = normalized.lower()
    if lowered in _COMMON_PLACEHOLDERS or any(
        marker in lowered for marker in _COMMON_PLACEHOLDER_SUBSTRINGS
    ):
        raise RuntimeError(
            f"Invalid configuration: {path} must not use placeholder values."
        )

    if (
        lowered.startswith("<set-")
        or lowered.startswith("<replace-")
        or (normalized.startswith("<") and normalized.endswith(">"))
    ):
        raise RuntimeError(
            f"Invalid configuration: {path} must not use placeholder values."
        )

    if len(normalized) < min_length:
        raise RuntimeError(
            f"Invalid configuration: {path} must contain at least "
            f"{min_length} characters."
        )

    return normalized


def validate_quart_secret_key(
    value: object,
    *,
    min_length: int = _DEFAULT_MIN_SECRET_KEY_LENGTH,
) -> str:
    """Validate Quart secret key quality for deployment-safe defaults."""
    return _validate_secret_value(
        value,
        path="quart.secret_key",
        min_length=min_length,
    )


def validate_matrix_secret_encryption_key(
    value: object,
    *,
    min_length: int = _DEFAULT_MIN_SECRET_KEY_LENGTH,
) -> str:
    """Validate Matrix secret-encryption key quality for safe deployments."""
    return _validate_secret_value(
        value,
        path="matrix.security.credentials.encryption_key",
        min_length=min_length,
    )


def validate_acp_managed_secret_encryption_key(
    value: object,
    *,
    min_length: int = _DEFAULT_MIN_SECRET_KEY_LENGTH,
) -> str:
    """Validate ACP managed-secret encryption root key quality."""
    return _validate_secret_value(
        value,
        path="acp.key_management.providers.managed.encryption_key",
        min_length=min_length,
    )
