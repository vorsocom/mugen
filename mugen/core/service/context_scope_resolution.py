"""Centralized context-scope resolution helpers for messaging ingress."""

from __future__ import annotations

__all__ = [
    "ContextScopeResolutionError",
    "ResolvedContextIngress",
    "context_scope_from_ingress_route",
    "resolve_ingress_route_context",
    "resolve_context_ingress",
]

from dataclasses import dataclass
from typing import Any, Mapping

from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import ContextScope
from mugen.core.contract.service.ingress_routing import (
    IngressRouteReason,
    IngressRouteResolution,
)
from mugen.core.service.ingress_routing import build_ingress_route_context

_GLOBAL_FALLBACK_REASONS = {
    IngressRouteReason.MISSING_IDENTIFIER.value,
    IngressRouteReason.MISSING_BINDING.value,
}

_FAIL_CLOSED_REASONS = {
    IngressRouteReason.INACTIVE_BINDING.value,
    IngressRouteReason.AMBIGUOUS_BINDING.value,
    IngressRouteReason.INVALID_TENANT_SLUG.value,
    IngressRouteReason.INACTIVE_TENANT.value,
    IngressRouteReason.UNAUTHORIZED_TENANT.value,
    IngressRouteReason.RESOLUTION_ERROR.value,
}


class ContextScopeResolutionError(RuntimeError):
    """Raised when tenant-safe scope resolution must fail closed."""

    def __init__(self, *, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.detail = detail
        message = reason_code if not detail else f"{reason_code}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ResolvedContextIngress:
    """Normalized ingress result passed into messaging/context runtime."""

    scope: ContextScope
    ingress_route: dict[str, Any]
    tenant_resolution: dict[str, Any]


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _route_value(route: Mapping[str, Any], key: str) -> str | None:
    return _normalize_optional_text(route.get(key))


def _default_ingress_route(
    *,
    platform: str,
    channel_key: str,
    identifier_claims: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tenant_id": str(GLOBAL_TENANT_ID),
        "tenant_slug": "global",
        "platform": platform,
        "channel_key": channel_key,
        "identifier_claims": dict(identifier_claims or {}),
        "channel_profile_id": None,
        "route_key": None,
        "binding_id": None,
    }


def _build_scope(
    *,
    platform: str,
    channel_key: str,
    room_id: str,
    sender_id: str,
    route: Mapping[str, Any],
    conversation_id: str | None = None,
    case_id: str | None = None,
    workflow_id: str | None = None,
) -> ContextScope:
    return ContextScope(
        tenant_id=str(route.get("tenant_id") or GLOBAL_TENANT_ID),
        platform=_route_value(route, "platform") or platform,
        channel_id=_route_value(route, "channel_key") or channel_key,
        room_id=room_id,
        sender_id=sender_id,
        conversation_id=conversation_id or room_id or sender_id,
        case_id=case_id,
        workflow_id=workflow_id,
    )


def resolve_context_ingress(
    *,
    platform: str,
    channel_key: str,
    room_id: str,
    sender_id: str,
    routing: IngressRouteResolution | None,
    source: str,
    conversation_id: str | None = None,
    case_id: str | None = None,
    workflow_id: str | None = None,
    identifier_claims: Mapping[str, Any] | None = None,
    allow_global_without_routing: bool = False,
) -> ResolvedContextIngress:
    """Resolve one ingress route outcome into ContextScope plus metadata."""
    if routing is not None and routing.ok and routing.result is not None:
        ingress_route = build_ingress_route_context(routing.result)
        tenant_resolution = {
            "mode": "resolved",
            "reason_code": None,
            "source": source,
        }
        ingress_route["tenant_resolution"] = tenant_resolution
        return ResolvedContextIngress(
            scope=_build_scope(
                platform=platform,
                channel_key=channel_key,
                room_id=room_id,
                sender_id=sender_id,
                route=ingress_route,
                conversation_id=conversation_id,
                case_id=case_id,
                workflow_id=workflow_id,
            ),
            ingress_route=ingress_route,
            tenant_resolution=tenant_resolution,
        )

    reason_code = _normalize_optional_text(
        None if routing is None else routing.reason_code
    )
    reason_detail = _normalize_optional_text(
        None if routing is None else routing.reason_detail
    )

    if routing is None:
        if allow_global_without_routing is not True:
            raise ContextScopeResolutionError(
                reason_code="missing_routing_service",
                detail="No ingress routing result was provided.",
            )
        reason_code = "no_routing_service"
    elif reason_code in _FAIL_CLOSED_REASONS:
        raise ContextScopeResolutionError(
            reason_code=reason_code,
            detail=reason_detail,
        )
    elif reason_code not in _GLOBAL_FALLBACK_REASONS:
        raise ContextScopeResolutionError(
            reason_code=reason_code or "route_unresolved",
            detail=reason_detail,
        )

    tenant_resolution = {
        "mode": "fallback_global",
        "reason_code": reason_code,
        "source": source,
    }
    ingress_route = _default_ingress_route(
        platform=platform,
        channel_key=channel_key,
        identifier_claims=identifier_claims,
    )
    ingress_route["tenant_resolution"] = tenant_resolution
    return ResolvedContextIngress(
        scope=_build_scope(
            platform=platform,
            channel_key=channel_key,
            room_id=room_id,
            sender_id=sender_id,
            route=ingress_route,
            conversation_id=conversation_id,
            case_id=case_id,
            workflow_id=workflow_id,
        ),
        ingress_route=ingress_route,
        tenant_resolution=tenant_resolution,
    )


def context_scope_from_ingress_route(
    *,
    platform: str,
    channel_key: str,
    room_id: str,
    sender_id: str,
    ingress_route: Mapping[str, Any] | None,
    ingress_metadata: Mapping[str, Any] | None = None,
    conversation_id: str | None = None,
    case_id: str | None = None,
    workflow_id: str | None = None,
    source: str = "messaging",
) -> ResolvedContextIngress:
    """Build ContextScope from an existing ingress-route envelope or global default."""
    normalized_route = (
        dict(ingress_route) if isinstance(ingress_route, Mapping) else None
    )
    metadata = dict(ingress_metadata or {})
    if normalized_route is None:
        tenant_resolution = {
            "mode": "fallback_global",
            "reason_code": "no_ingress_route",
            "source": source,
        }
        normalized_route = _default_ingress_route(
            platform=platform,
            channel_key=channel_key,
        )
    else:
        tenant_resolution = normalized_route.get("tenant_resolution")
        if not isinstance(tenant_resolution, dict):
            tenant_id = str(normalized_route.get("tenant_id") or GLOBAL_TENANT_ID)
            tenant_resolution = {
                "mode": (
                    "resolved"
                    if tenant_id != str(GLOBAL_TENANT_ID)
                    else "fallback_global"
                ),
                "reason_code": None
                if tenant_id != str(GLOBAL_TENANT_ID)
                else "implicit_global",
                "source": source,
            }
    normalized_route["tenant_resolution"] = tenant_resolution
    metadata["ingress_route"] = dict(normalized_route)
    metadata["tenant_resolution"] = dict(tenant_resolution)
    return ResolvedContextIngress(
        scope=_build_scope(
            platform=platform,
            channel_key=channel_key,
            room_id=room_id,
            sender_id=sender_id,
            route=normalized_route,
            conversation_id=conversation_id,
            case_id=case_id,
            workflow_id=workflow_id,
        ),
        ingress_route=normalized_route,
        tenant_resolution=dict(tenant_resolution),
    )


def resolve_ingress_route_context(
    *,
    platform: str,
    channel_key: str,
    routing: IngressRouteResolution | None,
    source: str,
    identifier_claims: Mapping[str, Any] | None = None,
    allow_global_without_routing: bool = False,
) -> dict[str, Any]:
    """Resolve an ingress route envelope with the same fallback policy as scope resolution."""
    resolved = resolve_context_ingress(
        platform=platform,
        channel_key=channel_key,
        room_id="",
        sender_id="",
        routing=routing,
        source=source,
        identifier_claims=identifier_claims,
        allow_global_without_routing=allow_global_without_routing,
    )
    return dict(resolved.ingress_route)
