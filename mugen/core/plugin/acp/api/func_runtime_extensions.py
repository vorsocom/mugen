"""Implements authenticated runtime extension status endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quart import abort, current_app

from mugen.bootstrap_state import get_extension_statuses
from mugen.core.api import api
from mugen.core.plugin.acp.api.decorator.auth import global_auth_required

_PUBLIC_FIELDS = (
    "token",
    "extension_type",
    "configured",
    "enabled",
    "available",
    "status",
    "reason",
)


def _extension_status_provider() -> Mapping[str, Mapping[str, object]]:
    """Return the current app's post-bootstrap extension status snapshot."""
    return get_extension_statuses(current_app)


def _public_status(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only client-safe fields from a runtime status record."""
    return {field: record.get(field) for field in _PUBLIC_FIELDS}


@api.get("/core/acp/v1/runtime/extensions")
@global_auth_required
async def runtime_extensions(
    status_provider=_extension_status_provider,
    **_,
) -> dict[str, list[dict[str, Any]]]:
    """Return client-safe status for every known or configured extension."""
    statuses = status_provider()
    return {
        "value": [
            _public_status(statuses[token])
            for token in sorted(statuses)
        ]
    }


@api.get("/core/acp/v1/runtime/extensions/<token>")
@global_auth_required
async def runtime_extension(
    token: str,
    status_provider=_extension_status_provider,
    **_,
) -> dict[str, Any]:
    """Return client-safe status for one known or configured extension."""
    normalized_token = str(token).strip().lower()
    status = status_provider().get(normalized_token)
    if status is None:
        abort(404, "Extension token not found.")
    return _public_status(status)
