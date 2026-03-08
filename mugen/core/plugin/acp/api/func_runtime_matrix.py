"""Implements Matrix runtime ACP endpoints."""

from __future__ import annotations

from typing import Any

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.api.decorator.auth import global_admin_required
from mugen.core.utility.client_profile_runtime import normalize_client_profile_id


def _matrix_client_provider():
    return di.container.matrix_client


def _logger_provider():
    return di.container.logging_gateway


@api.get("/core/acp/v1/runtime/matrix/device-verification-data")
@global_admin_required
async def matrix_device_verification_data(
    matrix_client_provider=_matrix_client_provider,
    logger_provider=_logger_provider,
    **_,
) -> dict[str, list[dict[str, str]]]:
    """Return device verification data for active Matrix runtime profiles."""
    matrix_client = matrix_client_provider()
    logger: ILoggingGateway = logger_provider()
    auth_user = _.get("auth_user")

    raw_client_profile_id = request.args.get("client_profile_id")
    client_profile_id = _normalize_requested_client_profile_id(raw_client_profile_id)
    if raw_client_profile_id not in [None, ""] and client_profile_id is None:
        logger.debug("Invalid Matrix device verification client_profile_id filter.")
        abort(400, "Invalid client_profile_id.")

    entries = await _collect_device_verification_data(
        matrix_client,
        client_profile_id=client_profile_id,
    )
    if client_profile_id is not None and not entries:
        logger.debug(
            "Matrix device verification lookup missed active runtime profile."
            f" auth_user={auth_user}"
            f" client_profile_id={client_profile_id}"
        )
        abort(404)

    logger.info(
        "ACP Matrix device verification lookup"
        f" auth_user={auth_user}"
        f" client_profile_id={client_profile_id or '*'}"
        f" result_count={len(entries)}"
    )
    return {
        "value": entries,
    }


def _normalize_requested_client_profile_id(raw_value: Any) -> str | None:
    if raw_value in [None, ""]:
        return None
    normalized = normalize_client_profile_id(raw_value)
    if normalized is None:
        return None
    return str(normalized)


async def _collect_device_verification_data(
    matrix_client: Any,
    *,
    client_profile_id: str | None,
) -> list[dict[str, str]]:
    resolver = getattr(matrix_client, "active_device_verification_data", None)
    if callable(resolver):
        rows = await resolver(client_profile_id=client_profile_id)
        return _normalize_entries(rows)

    single_resolver = getattr(matrix_client, "device_verification_data", None)
    if not callable(single_resolver):
        return []
    entry = _normalize_entry(single_resolver())
    if entry is None:
        return []
    if (
        client_profile_id is not None
        and entry.get("client_profile_id", "") != client_profile_id
    ):
        return []
    return [entry]


def _normalize_entries(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, str]] = []
    for row in rows:
        entry = _normalize_entry(row)
        if entry is not None:
            normalized.append(entry)
    return normalized


def _normalize_entry(row: Any) -> dict[str, str] | None:
    if not isinstance(row, dict):
        return None
    client_profile_id = str(row.get("client_profile_id") or "").strip()
    if client_profile_id == "":
        return None
    return {
        "client_profile_id": client_profile_id,
        "client_profile_key": str(row.get("client_profile_key") or ""),
        "recipient_user_id": str(row.get("recipient_user_id") or ""),
        "public_name": str(row.get("public_name") or ""),
        "session_id": str(row.get("session_id") or ""),
        "session_key": str(row.get("session_key") or ""),
    }
