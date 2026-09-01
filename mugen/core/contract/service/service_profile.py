"""Contracts for tenant-scoped Service Profile runtime resolution."""

from __future__ import annotations

__all__ = [
    "IServiceProfileEntitlementService",
    "IServiceProfileResolver",
    "ServiceProfileEntitlement",
    "ServiceProfileEntitlementReason",
    "ServiceProfileEntitlementResolution",
    "ServiceProfileResolution",
    "ServiceProfileResolutionReason",
    "ServiceProfileResult",
]

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ServiceProfileResolutionReason(str, Enum):
    """Fail-closed Service Profile ingress resolution reasons."""

    MISSING_ASSIGNMENT = "missing_assignment"
    AMBIGUOUS_ASSIGNMENT = "ambiguous_assignment"
    INACTIVE_BINDING = "inactive_binding"
    INACTIVE_PROFILE = "inactive_profile"
    RESOLUTION_ERROR = "resolution_error"


@dataclass(frozen=True, slots=True)
class ServiceProfileResult:
    """Resolved active Service Profile identity."""

    tenant_id: uuid.UUID
    service_profile_id: uuid.UUID
    key: str
    display_name: str


@dataclass(frozen=True, slots=True)
class ServiceProfileResolution:
    """Deterministic Service Profile ingress resolution outcome."""

    ok: bool
    result: ServiceProfileResult | None = None
    reason_code: str | None = None


class IServiceProfileResolver(ABC):
    """Resolve one active Service Profile from an exact tenant/binding pair."""

    @abstractmethod
    async def resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        ingress_binding_id: uuid.UUID,
    ) -> ServiceProfileResolution:
        """Resolve an active profile or return a fail-closed reason."""


class ServiceProfileEntitlementReason(str, Enum):
    """Fail-closed Service Profile entitlement resolution reasons."""

    INACTIVE_PROFILE = "inactive_profile"
    MISSING_ASSIGNMENT = "missing_assignment"
    AMBIGUOUS_ASSIGNMENT = "ambiguous_assignment"
    INACTIVE_SUBSCRIPTION = "inactive_subscription"
    INACTIVE_ACCOUNT = "inactive_account"
    INACTIVE_PRICE = "inactive_price"
    INACTIVE_PRODUCT = "inactive_product"
    CATALOG_DRIFT = "catalog_drift"
    RESOLUTION_ERROR = "resolution_error"


@dataclass(frozen=True, slots=True)
class ServiceProfileEntitlement:
    """Exact commercial allocation and catalog provenance for one profile."""

    tenant_id: uuid.UUID
    service_profile_id: uuid.UUID
    service_profile_subscription_id: uuid.UUID
    billing_account_id: uuid.UUID
    billing_subscription_id: uuid.UUID
    billing_price_id: uuid.UUID
    billing_product_id: uuid.UUID
    product_code: str
    subscription_status: str
    current_period_start: datetime
    current_period_end: datetime


@dataclass(frozen=True, slots=True)
class ServiceProfileEntitlementResolution:
    """Deterministic Service Profile entitlement resolution outcome."""

    ok: bool
    result: ServiceProfileEntitlement | None = None
    reason_code: str | None = None


class IServiceProfileEntitlementService(ABC):
    """Resolve one exact, currently eligible Subscription allocation."""

    @abstractmethod
    async def resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        service_profile_id: uuid.UUID,
        product_code: str,
    ) -> ServiceProfileEntitlementResolution:
        """Resolve current entitlement provenance or fail closed."""
