"""Contracts for tenant-aware ingress route resolution."""

__all__ = [
    "IngressRouteReason",
    "IngressRouteRequest",
    "IngressRouteResult",
    "IngressRouteResolution",
    "IIngressRoutingService",
]

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping
import uuid


class IngressRouteReason(str, Enum):
    """Standardized resolver reason codes."""

    MISSING_IDENTIFIER = "missing_identifier"
    MISSING_BINDING = "missing_binding"
    INACTIVE_BINDING = "inactive_binding"
    AMBIGUOUS_BINDING = "ambiguous_binding"
    INVALID_TENANT_SLUG = "invalid_tenant_slug"
    INACTIVE_TENANT = "inactive_tenant"
    UNAUTHORIZED_TENANT = "unauthorized_tenant"
    RESOLUTION_ERROR = "resolution_error"


@dataclass(frozen=True, slots=True)
class IngressRouteRequest:
    """Route resolution request contract."""

    platform: str
    channel_key: str
    identifier_type: str
    identifier_value: str | None
    tenant_slug: str | None = None
    auth_user_id: uuid.UUID | None = None
    require_active_binding: bool = True
    claims: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngressRouteResult:
    """Resolved ingress route context."""

    tenant_id: uuid.UUID
    tenant_slug: str
    platform: str
    channel_key: str
    identifier_claims: dict[str, str]
    channel_profile_id: uuid.UUID | None = None
    client_profile_id: uuid.UUID | None = None
    route_key: str | None = None
    binding_id: uuid.UUID | None = None
    client_profile_key: str | None = None


@dataclass(frozen=True, slots=True)
class IngressRouteResolution:
    """Deterministic route resolution outcome."""

    ok: bool
    result: IngressRouteResult | None = None
    reason_code: str | None = None
    reason_detail: str | None = None


class IIngressRoutingService(ABC):
    """Contract for ingress route resolution services."""

    @abstractmethod
    async def resolve(self, request: IngressRouteRequest) -> IngressRouteResolution:
        """Resolve one ingress route request."""
