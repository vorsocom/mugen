"""Helpers for ACP-owned messaging client profile runtime routing."""

from __future__ import annotations

__all__ = [
    "client_profile_id_from_ingress_route",
    "client_profile_scope",
    "get_active_client_profile_id",
    "normalize_client_profile_id",
]

import contextlib
import contextvars
import uuid
from typing import Any, Mapping

_ACTIVE_CLIENT_PROFILE_ID: contextvars.ContextVar[uuid.UUID | None] = (
    contextvars.ContextVar("mugen_active_client_profile_id", default=None)
)


def normalize_client_profile_id(value: object) -> uuid.UUID | None:
    """Normalize one client profile UUID value."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value).strip())
    except (AttributeError, TypeError, ValueError):
        return None


def client_profile_id_from_ingress_route(
    ingress_route: Mapping[str, Any] | None,
) -> uuid.UUID | None:
    """Resolve client profile id from an ingress-route envelope."""
    if not isinstance(ingress_route, Mapping):
        return None
    return normalize_client_profile_id(ingress_route.get("client_profile_id"))


def get_active_client_profile_id() -> uuid.UUID | None:
    """Resolve the task-local active client profile id."""
    return normalize_client_profile_id(_ACTIVE_CLIENT_PROFILE_ID.get())


@contextlib.contextmanager
def client_profile_scope(client_profile_id: object | None):
    """Temporarily bind one active client profile id to the current task."""
    token = _ACTIVE_CLIENT_PROFILE_ID.set(
        normalize_client_profile_id(client_profile_id)
    )
    try:
        yield
    finally:
        _ACTIVE_CLIENT_PROFILE_ID.reset(token)
