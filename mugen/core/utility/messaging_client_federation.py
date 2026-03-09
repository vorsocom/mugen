"""Helpers for MessagingClientProfile Matrix federation policy settings."""

from __future__ import annotations

__all__ = [
    "MessagingClientFederationPolicy",
    "normalize_messaging_client_federation",
    "parse_matrix_sender_domain",
    "resolve_messaging_client_federation_policy",
]

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

_SUPPORTED_KEYS = frozenset({"allowed", "denied"})


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


def _normalize_domain_list(
    value: object,
    *,
    field_name: str,
    require_non_empty: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"{field_name} must be an array of strings.")

    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        domain = _normalize_optional_text(item)
        if domain is None:
            raise RuntimeError(f"{field_name}[{index}] must be a non-empty string.")
        if domain in seen:
            continue
        seen.add(domain)
        normalized.append(domain)

    if require_non_empty is True and not normalized:
        raise RuntimeError(f"{field_name} must be a non-empty array of strings.")
    return normalized


def parse_matrix_sender_domain(sender_id: object) -> str | None:
    """Extract the Matrix homeserver domain from one sender MXID."""
    if not isinstance(sender_id, str):
        return None

    local_part, separator, domain_part = sender_id.partition(":")
    if separator == "" or not local_part.startswith("@") or domain_part.strip() == "":
        return None
    return domain_part


@dataclass(frozen=True, slots=True)
class MessagingClientFederationPolicy:
    """Normalized Matrix federation policy for one messaging client profile."""

    allowed: tuple[str, ...]
    denied: tuple[str, ...] = ()

    def allows_domain(self, sender_domain: object) -> bool:
        """Return whether the given Matrix homeserver domain is allowed."""
        if not isinstance(sender_domain, str) or sender_domain.strip() == "":
            return False
        return sender_domain in self.allowed and sender_domain not in self.denied

    def allows_sender(self, sender_id: object) -> bool:
        """Return whether the given sender MXID is allowed."""
        return self.allows_domain(parse_matrix_sender_domain(sender_id))


def normalize_messaging_client_federation(
    value: object,
    *,
    field_name: str = "federation",
    require_allowed: bool = True,
) -> dict[str, Any]:
    """Normalize one MessagingClientProfile Matrix federation policy payload."""
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

    allowed = _normalize_domain_list(
        normalized_payload.get("allowed", []),
        field_name=f"{field_name}.allowed",
        require_non_empty=require_allowed,
    )
    denied = _normalize_domain_list(
        normalized_payload.get("denied", []),
        field_name=f"{field_name}.denied",
        require_non_empty=False,
    )
    return {
        "allowed": allowed,
        "denied": denied,
    }


def resolve_messaging_client_federation_policy(
    value: object,
    *,
    field_name: str = "federation",
) -> MessagingClientFederationPolicy:
    """Resolve one runtime Matrix federation policy from a mapping or namespace."""
    normalized = normalize_messaging_client_federation(
        value,
        field_name=field_name,
        require_allowed=True,
    )
    return MessagingClientFederationPolicy(
        allowed=tuple(normalized["allowed"]),
        denied=tuple(normalized["denied"]),
    )
