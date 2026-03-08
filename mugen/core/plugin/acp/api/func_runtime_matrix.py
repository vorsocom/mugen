"""Implements Matrix runtime ACP endpoints."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from quart import abort, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.api.decorator.auth import (
    global_admin_required,
    global_auth_required,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service import (
    ITenantMembershipService,
    IUserService,
)
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.utility.client_profile_runtime import normalize_client_profile_id

_EDM_TENANT_MEMBERSHIP = "ACP.TenantMembership"
_EDM_USER = "ACP.User"
_INTERNAL_TENANT_ID_KEY = "tenant_id"
_ROLE_ADMINISTRATOR = "administrator"
_TENANT_ADMIN_ROLES = frozenset({"admin", "owner"})


def _config_provider():
    return di.container.config


def _matrix_client_provider():
    return di.container.matrix_client


def _logger_provider():
    return di.container.logging_gateway


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


def _user_service_provider(
    registry_provider=_registry_provider,
) -> IUserService:
    registry: IAdminRegistry = registry_provider()
    return registry.get_edm_service(
        registry.get_resource_by_type(_EDM_USER).service_key
    )


def _tenant_membership_service_provider(
    registry_provider=_registry_provider,
) -> ITenantMembershipService:
    registry: IAdminRegistry = registry_provider()
    return registry.get_edm_service(
        registry.get_resource_by_type(_EDM_TENANT_MEMBERSHIP).service_key
    )


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


@api.get("/core/acp/v1/tenants/<tenant_id>/runtime/matrix/device-verification-data")
@global_auth_required
async def tenant_matrix_device_verification_data(
    tenant_id: str,
    auth_user: str,
    config_provider=_config_provider,
    matrix_client_provider=_matrix_client_provider,
    logger_provider=_logger_provider,
    tenant_membership_service_provider=_tenant_membership_service_provider,
    user_service_provider=_user_service_provider,
    **_,
) -> dict[str, list[dict[str, str]]]:
    """Return tenant-owned Matrix device verification data."""
    config: SimpleNamespace = config_provider()
    matrix_client = matrix_client_provider()
    logger: ILoggingGateway = logger_provider()

    normalized_tenant_id = _normalize_requested_tenant_id(tenant_id)
    if normalized_tenant_id is None:
        logger.debug("Invalid Matrix device verification tenant_id filter.")
        abort(400, "Invalid tenant_id.")

    raw_client_profile_id = request.args.get("client_profile_id")
    client_profile_id = _normalize_requested_client_profile_id(raw_client_profile_id)
    if raw_client_profile_id not in [None, ""] and client_profile_id is None:
        logger.debug("Invalid Matrix device verification client_profile_id filter.")
        abort(400, "Invalid client_profile_id.")

    await _authorize_tenant_runtime_lookup(
        auth_user=auth_user,
        config=config,
        logger=logger,
        tenant_id=normalized_tenant_id,
        tenant_membership_service_provider=tenant_membership_service_provider,
        user_service_provider=user_service_provider,
    )

    entries = await _collect_device_verification_data(
        matrix_client,
        client_profile_id=client_profile_id,
        include_internal=True,
    )
    entries = _filter_entries_for_tenant(
        entries,
        tenant_id=normalized_tenant_id,
    )
    if client_profile_id is not None and not entries:
        logger.debug(
            "Tenant Matrix device verification lookup missed active runtime profile."
            f" auth_user={auth_user}"
            f" tenant_id={normalized_tenant_id}"
            f" client_profile_id={client_profile_id}"
        )
        abort(404)

    public_entries = _normalize_entries(entries)
    logger.info(
        "Tenant ACP Matrix device verification lookup"
        f" auth_user={auth_user}"
        f" tenant_id={normalized_tenant_id}"
        f" client_profile_id={client_profile_id or '*'}"
        f" result_count={len(public_entries)}"
    )
    return {
        "value": public_entries,
    }


async def _authorize_tenant_runtime_lookup(
    *,
    auth_user: str,
    config: SimpleNamespace,
    logger: ILoggingGateway,
    tenant_id: str,
    tenant_membership_service_provider,
    user_service_provider,
) -> None:
    auth_user_uuid = _normalize_uuid_value(auth_user)
    if auth_user_uuid is None:
        logger.error("Invalid auth_user supplied to tenant Matrix runtime lookup.")
        abort(500)

    try:
        user = await user_service_provider().get_expanded({"id": auth_user_uuid})
    except SQLAlchemyError as exc:
        logger.error(exc)
        abort(500)

    if _is_global_admin(user, config=config):
        return

    try:
        membership = await tenant_membership_service_provider().get(
            {
                "tenant_id": uuid.UUID(tenant_id),
                "user_id": auth_user_uuid,
                "status": "active",
            }
        )
    except SQLAlchemyError as exc:
        logger.error(exc)
        abort(500)

    if membership is None:
        logger.warning(
            "Unauthorized tenant Matrix device verification lookup."
            f" auth_user={auth_user}"
            f" tenant_id={tenant_id}"
            " reason=missing_active_membership"
        )
        abort(403)

    role_in_tenant = str(
        getattr(membership, "role_in_tenant", "") or ""
    ).strip().lower()
    if role_in_tenant not in _TENANT_ADMIN_ROLES:
        logger.warning(
            "Unauthorized tenant Matrix device verification lookup."
            f" auth_user={auth_user}"
            f" tenant_id={tenant_id}"
            f" role_in_tenant={role_in_tenant or '?'}"
        )
        abort(403)


def _normalize_requested_client_profile_id(raw_value: Any) -> str | None:
    if raw_value in [None, ""]:
        return None
    normalized = normalize_client_profile_id(raw_value)
    if normalized is None:
        return None
    return str(normalized)


def _normalize_requested_tenant_id(raw_value: Any) -> str | None:
    normalized = _normalize_uuid_value(raw_value)
    if normalized is None:
        return None
    return str(normalized)


def _normalize_uuid_value(raw_value: Any) -> uuid.UUID | None:
    if raw_value in [None, ""]:
        return None
    try:
        return uuid.UUID(str(raw_value).strip())
    except (AttributeError, TypeError, ValueError):
        return None


async def _collect_device_verification_data(
    matrix_client: Any,
    *,
    client_profile_id: str | None,
    include_internal: bool = False,
) -> list[dict[str, str]]:
    resolver = getattr(matrix_client, "active_device_verification_data", None)
    if callable(resolver):
        if include_internal:
            rows = await resolver(
                client_profile_id=client_profile_id,
                include_internal=True,
            )
            entries = _normalize_entries(rows, include_internal=True)
            return _filter_entries_for_client_profile(
                entries,
                client_profile_id=client_profile_id,
            )

        rows = await resolver(client_profile_id=client_profile_id)
        entries = _normalize_entries(rows)
        return _filter_entries_for_client_profile(
            entries,
            client_profile_id=client_profile_id,
        )

    single_resolver = getattr(matrix_client, "device_verification_data", None)
    if not callable(single_resolver):
        return []
    entry = _normalize_entry(
        single_resolver(),
        include_internal=include_internal,
    )
    if entry is None:
        return []
    if (
        client_profile_id is not None
        and entry.get("client_profile_id", "") != client_profile_id
    ):
        return []
    return [entry]


def _normalize_entries(
    rows: Any,
    *,
    include_internal: bool = False,
) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, str]] = []
    for row in rows:
        entry = _normalize_entry(row, include_internal=include_internal)
        if entry is not None:
            normalized.append(entry)
    return normalized


def _normalize_entry(
    row: Any,
    *,
    include_internal: bool = False,
) -> dict[str, str] | None:
    if not isinstance(row, dict):
        return None
    client_profile_id = _normalize_requested_client_profile_id(
        row.get("client_profile_id")
    )
    if client_profile_id is None:
        return None
    entry = {
        "client_profile_id": client_profile_id,
        "client_profile_key": str(row.get("client_profile_key") or ""),
        "recipient_user_id": str(row.get("recipient_user_id") or ""),
        "public_name": str(row.get("public_name") or ""),
        "session_id": str(row.get("session_id") or ""),
        "session_key": str(row.get("session_key") or ""),
    }
    if include_internal:
        tenant_id = _normalize_requested_tenant_id(row.get(_INTERNAL_TENANT_ID_KEY))
        if tenant_id is not None:
            entry[_INTERNAL_TENANT_ID_KEY] = tenant_id
    return entry


def _filter_entries_for_tenant(
    entries: list[dict[str, str]],
    *,
    tenant_id: str,
) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for entry in entries:
        if entry.get(_INTERNAL_TENANT_ID_KEY) != tenant_id:
            continue
        filtered.append(dict(entry))
    return filtered


def _filter_entries_for_client_profile(
    entries: list[dict[str, str]],
    *,
    client_profile_id: str | None,
) -> list[dict[str, str]]:
    if client_profile_id is None:
        return entries
    filtered: list[dict[str, str]] = []
    for entry in entries:
        if entry.get("client_profile_id") != client_profile_id:
            continue
        filtered.append(dict(entry))
    return filtered


def _is_global_admin(
    user: Any,
    *,
    config: SimpleNamespace,
) -> bool:
    if user is None:
        return False
    admin_ns = AdminNs(config.acp.namespace)
    global_roles = [
        f"{role.namespace}:{role.name}"
        for role in (getattr(user, "global_roles", None) or [])
    ]
    return admin_ns.key(_ROLE_ADMINISTRATOR) in global_roles
