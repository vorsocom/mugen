"""Helpers for MessagingClientProfile user-access policy settings."""

from __future__ import annotations

__all__ = [
    "MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL",
    "MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL_EXCEPT",
    "MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY",
    "MESSAGING_CLIENT_USER_ACCESS_MODES",
    "MessagingClientUserAccessPolicy",
    "normalize_messaging_client_user_access",
    "resolve_messaging_client_user_access_policy",
]

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL = "allow-all"
MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL_EXCEPT = "allow-all-except"
MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY = "allow-only"
MESSAGING_CLIENT_USER_ACCESS_MODES = frozenset(
    {
        MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL,
        MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL_EXCEPT,
        MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY,
    }
)

_SUPPORTED_KEYS = frozenset({"mode", "users", "denied_message"})


def _normalize_required_text(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if text == "":
        raise RuntimeError(f"{field_name} must be a non-empty string.")
    return text


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_mapping(
    value: object,
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, SimpleNamespace):
        return vars(value)
    raise RuntimeError(f"{field_name} must be a table.")


def _normalize_mode(value: object, *, field_name: str) -> str:
    normalized = _normalize_required_text(
        value,
        field_name=field_name,
    ).lower()
    normalized = normalized.replace("_", "-")
    if normalized in MESSAGING_CLIENT_USER_ACCESS_MODES:
        return normalized
    supported = ", ".join(sorted(MESSAGING_CLIENT_USER_ACCESS_MODES))
    raise RuntimeError(f"{field_name} must be one of: {supported}.")


def _normalize_users(
    value: object,
    *,
    field_name: str,
) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"{field_name} must be an array of strings.")

    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        user_id = _normalize_optional_text(item)
        if user_id is None:
            raise RuntimeError(f"{field_name}[{index}] must be a non-empty string.")
        if user_id in seen:
            continue
        seen.add(user_id)
        normalized.append(user_id)
    return normalized


@dataclass(frozen=True, slots=True)
class MessagingClientUserAccessPolicy:
    """Normalized sender access policy for one messaging client profile."""

    mode: str = MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL
    users: tuple[str, ...] = ()
    denied_message: str | None = None

    def allows(self, user_id: object) -> bool:
        """Return whether the given sender identifier is allowed."""
        normalized_user_id = _normalize_optional_text(user_id)
        if normalized_user_id is None:
            return False
        if self.mode == MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL:
            return True
        if self.mode == MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL_EXCEPT:
            return normalized_user_id not in self.users
        return normalized_user_id in self.users


def normalize_messaging_client_user_access(
    value: object,
    *,
    field_name: str = "user_access",
    allow_denied_message: bool = False,
) -> dict[str, Any]:
    """Normalize one MessagingClientProfile user-access policy payload."""
    payload = _normalize_mapping(value, field_name=field_name)
    normalized_payload: dict[str, Any] = {}
    for raw_key, raw_value in payload.items():
        key = _normalize_required_text(
            raw_key,
            field_name=f"{field_name} key",
        ).lower()
        if key in normalized_payload:
            raise RuntimeError(f"{field_name} contains duplicate key {key!r}.")
        if key not in _SUPPORTED_KEYS:
            raise RuntimeError(f"{field_name}.{key} is not supported.")
        normalized_payload[key] = raw_value

    mode = _normalize_mode(
        normalized_payload.get("mode"),
        field_name=f"{field_name}.mode",
    )
    users = _normalize_users(
        normalized_payload.get("users", []),
        field_name=f"{field_name}.users",
    )
    denied_message = None
    raw_denied_message = normalized_payload.get("denied_message")
    if raw_denied_message is not None:
        if allow_denied_message is not True:
            raise RuntimeError(f"{field_name}.denied_message is not supported.")
        denied_message = _normalize_required_text(
            raw_denied_message,
            field_name=f"{field_name}.denied_message",
        )

    if mode == MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL:
        if users:
            raise RuntimeError(
                f"{field_name}.users must be empty when mode=allow-all."
            )
        if denied_message is not None:
            raise RuntimeError(
                f"{field_name}.denied_message is only supported when mode denies users."
            )
    elif not users:
        raise RuntimeError(
            f"{field_name}.users must be a non-empty array of strings when "
            f"mode={mode}."
        )

    normalized: dict[str, Any] = {
        "mode": mode,
        "users": users,
    }
    if denied_message is not None:
        normalized["denied_message"] = denied_message
    return normalized


def resolve_messaging_client_user_access_policy(
    value: object | None,
    *,
    field_name: str = "user_access",
    allow_denied_message: bool = False,
) -> MessagingClientUserAccessPolicy:
    """Resolve one runtime user-access policy from a mapping or namespace."""
    if value is None:
        return MessagingClientUserAccessPolicy()
    normalized = normalize_messaging_client_user_access(
        value,
        field_name=field_name,
        allow_denied_message=allow_denied_message,
    )
    return MessagingClientUserAccessPolicy(
        mode=normalized["mode"],
        users=tuple(normalized["users"]),
        denied_message=normalized.get("denied_message"),
    )
