"""Shared tenant-aware ingress route resolver."""

from __future__ import annotations

__all__ = [
    "DefaultIngressRoutingService",
    "build_ingress_route_context",
    "build_ingress_route_message_context_item",
    "merge_ingress_route_metadata",
]

from typing import Any, Mapping
import uuid

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.contract.service.ingress_routing import (
    IIngressRoutingService,
    IngressRouteReason,
    IngressRouteRequest,
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.constants import GLOBAL_TENANT_ID

_TABLE_TENANT = "admin_tenant"
_TABLE_TENANT_MEMBERSHIP = "admin_tenant_membership"
_TABLE_INGRESS_BINDING = "channel_orchestration_ingress_binding"
_TABLE_CHANNEL_PROFILE = "channel_orchestration_channel_profile"


def _normalize_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized == "":
        return None
    return normalized


def _normalize_required_text(value: Any) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise ValueError("value is required")
    return normalized


def _normalize_optional_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_claims(claims: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in claims.items():
        key_text = _normalize_optional_text(key)
        value_text = _normalize_optional_text(value)
        if key_text is None or value_text is None:
            continue
        normalized[key_text] = value_text
    return normalized


def build_ingress_route_context(result: IngressRouteResult) -> dict[str, Any]:
    """Build a stable ingress-route envelope for downstream consumers."""
    return {
        "tenant_id": str(result.tenant_id),
        "tenant_slug": result.tenant_slug,
        "platform": result.platform,
        "channel_key": result.channel_key,
        "identifier_claims": dict(result.identifier_claims),
        "channel_profile_id": (
            str(result.channel_profile_id)
            if result.channel_profile_id is not None
            else None
        ),
        "route_key": result.route_key,
        "binding_id": str(result.binding_id) if result.binding_id is not None else None,
    }


def build_ingress_route_message_context_item(result: IngressRouteResult) -> dict[str, Any]:
    """Create a `message_context` item for ingress route context."""
    return {
        "type": "ingress_route",
        "content": build_ingress_route_context(result),
    }


def merge_ingress_route_metadata(
    metadata: Mapping[str, Any] | None,
    result: IngressRouteResult,
) -> dict[str, Any]:
    """Merge ingress-route envelope into message metadata for media payloads."""
    merged: dict[str, Any] = {}
    if isinstance(metadata, Mapping):
        merged.update(dict(metadata))
    merged["ingress_route"] = build_ingress_route_context(result)
    return merged


class DefaultIngressRoutingService(IIngressRoutingService):
    """Default implementation backed by ACP/channel-orchestration tables."""

    def __init__(
        self,
        *,
        relational_storage_gateway: IRelationalStorageGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._rsg = relational_storage_gateway
        self._logging_gateway = logging_gateway

    def _fail(
        self,
        reason: IngressRouteReason,
        *,
        detail: str | None = None,
    ) -> IngressRouteResolution:
        return IngressRouteResolution(
            ok=False,
            reason_code=reason.value,
            reason_detail=detail,
        )

    @staticmethod
    def _tenant_slug_from_row(tenant_row: Mapping[str, Any] | None) -> str | None:
        if tenant_row is None:
            return None
        return _normalize_optional_text(tenant_row.get("slug"))

    @staticmethod
    def _tenant_active(tenant_row: Mapping[str, Any] | None) -> bool:
        if tenant_row is None:
            return False
        status = _normalize_optional_text(tenant_row.get("status"))
        return status == "active"

    async def _get_tenant_by_slug(self, tenant_slug: str) -> Mapping[str, Any] | None:
        return await self._rsg.get_one(
            _TABLE_TENANT,
            {"slug": tenant_slug},
            columns=("id", "slug", "status"),
        )

    async def _get_tenant_by_id(self, tenant_id: uuid.UUID) -> Mapping[str, Any] | None:
        return await self._rsg.get_one(
            _TABLE_TENANT,
            {"id": tenant_id},
            columns=("id", "slug", "status"),
        )

    async def _has_active_membership(
        self,
        *,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID | None,
    ) -> bool:
        if auth_user_id is None:
            return True
        if tenant_id == GLOBAL_TENANT_ID:
            return True
        membership = await self._rsg.get_one(
            _TABLE_TENANT_MEMBERSHIP,
            {
                "tenant_id": tenant_id,
                "user_id": auth_user_id,
                "status": "active",
            },
            columns=("id",),
        )
        return membership is not None

    async def _resolve_route_key(
        self,
        *,
        tenant_id: uuid.UUID,
        binding_row: Mapping[str, Any],
    ) -> str | None:
        attributes = binding_row.get("attributes")
        if isinstance(attributes, Mapping):
            configured_route_key = _normalize_optional_text(attributes.get("route_key"))
            if configured_route_key is not None:
                return configured_route_key

        channel_profile_id = _normalize_optional_uuid(binding_row.get("channel_profile_id"))
        if channel_profile_id is None:
            return None

        profile = await self._rsg.get_one(
            _TABLE_CHANNEL_PROFILE,
            {
                "tenant_id": tenant_id,
                "id": channel_profile_id,
                "is_active": True,
            },
            columns=("route_default_key",),
        )
        if profile is None:
            return None
        return _normalize_optional_text(profile.get("route_default_key"))

    async def _resolve_binding(
        self,
        *,
        channel_key: str,
        identifier_type: str,
        identifier_value: str,
        tenant_id: uuid.UUID | None,
    ) -> tuple[Mapping[str, Any] | None, IngressRouteReason | None]:
        active_where: dict[str, Any] = {
            "channel_key": channel_key,
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
            "is_active": True,
        }
        if tenant_id is not None:
            active_where["tenant_id"] = tenant_id

        active_rows = await self._rsg.find_many(
            _TABLE_INGRESS_BINDING,
            filter_groups=[FilterGroup(where=active_where)],
            limit=3,
        )
        if len(active_rows) > 1:
            return None, IngressRouteReason.AMBIGUOUS_BINDING
        if len(active_rows) == 1:
            return active_rows[0], None

        inactive_where = dict(active_where)
        inactive_where["is_active"] = False
        inactive_rows = await self._rsg.find_many(
            _TABLE_INGRESS_BINDING,
            filter_groups=[FilterGroup(where=inactive_where)],
            limit=1,
        )
        if inactive_rows:
            return None, IngressRouteReason.INACTIVE_BINDING

        return None, IngressRouteReason.MISSING_BINDING

    async def resolve(self, request: IngressRouteRequest) -> IngressRouteResolution:
        try:
            platform = _normalize_required_text(request.platform)
            channel_key = _normalize_required_text(request.channel_key)
            identifier_type = _normalize_required_text(request.identifier_type)
            identifier_value = _normalize_optional_text(request.identifier_value)
            tenant_slug = _normalize_optional_text(request.tenant_slug)

            if request.require_active_binding and identifier_value is None:
                return self._fail(IngressRouteReason.MISSING_IDENTIFIER)

            tenant_row: Mapping[str, Any] | None = None
            tenant_id: uuid.UUID | None = None

            if tenant_slug is not None:
                tenant_row = await self._get_tenant_by_slug(tenant_slug)
                if tenant_row is None:
                    return self._fail(IngressRouteReason.INVALID_TENANT_SLUG)
                if not self._tenant_active(tenant_row):
                    return self._fail(IngressRouteReason.INACTIVE_TENANT)
                tenant_id = _normalize_optional_uuid(tenant_row.get("id"))
                if tenant_id is None:
                    return self._fail(IngressRouteReason.INACTIVE_TENANT)
                authorized = await self._has_active_membership(
                    tenant_id=tenant_id,
                    auth_user_id=request.auth_user_id,
                )
                if not authorized:
                    return self._fail(IngressRouteReason.UNAUTHORIZED_TENANT)

            binding_row: Mapping[str, Any] | None = None
            if request.require_active_binding:
                binding_row, binding_error = await self._resolve_binding(
                    channel_key=channel_key,
                    identifier_type=identifier_type,
                    identifier_value=identifier_value,
                    tenant_id=tenant_id,
                )
                if binding_error is not None:
                    return self._fail(binding_error)
                if binding_row is None:
                    return self._fail(IngressRouteReason.MISSING_BINDING)

                binding_tenant_id = _normalize_optional_uuid(binding_row.get("tenant_id"))
                if binding_tenant_id is None:
                    return self._fail(IngressRouteReason.INACTIVE_TENANT)
                tenant_id = binding_tenant_id
                tenant_row = await self._get_tenant_by_id(tenant_id)
                if tenant_row is None or not self._tenant_active(tenant_row):
                    return self._fail(IngressRouteReason.INACTIVE_TENANT)
                authorized = await self._has_active_membership(
                    tenant_id=tenant_id,
                    auth_user_id=request.auth_user_id,
                )
                if not authorized:
                    return self._fail(IngressRouteReason.UNAUTHORIZED_TENANT)
            else:
                if tenant_id is None:
                    tenant_id = GLOBAL_TENANT_ID
                    tenant_row = await self._get_tenant_by_id(tenant_id)
                    if tenant_row is None:
                        # Keep generic web traffic alive even before global-tenant seeding.
                        tenant_row = {"id": tenant_id, "slug": "global", "status": "active"}
                    elif not self._tenant_active(tenant_row):
                        return self._fail(IngressRouteReason.INACTIVE_TENANT)

            resolved_tenant_slug = self._tenant_slug_from_row(tenant_row) or "global"

            claims = _normalize_claims(request.claims)
            claims.setdefault("identifier_type", identifier_type)
            if identifier_value is not None:
                claims.setdefault("identifier_value", identifier_value)

            route_key = None
            channel_profile_id = None
            binding_id = None
            if binding_row is not None:
                channel_profile_id = _normalize_optional_uuid(
                    binding_row.get("channel_profile_id")
                )
                binding_id = _normalize_optional_uuid(binding_row.get("id"))
                route_key = await self._resolve_route_key(
                    tenant_id=tenant_id,
                    binding_row=binding_row,
                )

            return IngressRouteResolution(
                ok=True,
                result=IngressRouteResult(
                    tenant_id=tenant_id,
                    tenant_slug=resolved_tenant_slug,
                    platform=platform,
                    channel_key=channel_key,
                    identifier_claims=claims,
                    channel_profile_id=channel_profile_id,
                    route_key=route_key,
                    binding_id=binding_id,
                ),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "Ingress route resolution failed unexpectedly "
                f"(platform={request.platform!r} channel_key={request.channel_key!r} "
                f"identifier_type={request.identifier_type!r}): "
                f"{type(exc).__name__}: {exc}"
            )
            return self._fail(
                IngressRouteReason.RESOLUTION_ERROR,
                detail=f"{type(exc).__name__}: {exc}",
            )
