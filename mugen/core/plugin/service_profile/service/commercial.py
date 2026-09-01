"""Shared live Billing validation for Service Profile allocations."""

from __future__ import annotations

__all__ = [
    "CommercialContract",
    "CommercialValidationError",
    "load_commercial_contract",
    "normalize_product_code",
]

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.service.service_profile import ServiceProfileEntitlementReason


def normalize_product_code(value: object) -> str:
    """Normalize the canonical Product code used for allocation identity."""
    normalized = str(value or "").strip().casefold()
    if normalized == "":
        raise CommercialValidationError(
            ServiceProfileEntitlementReason.INACTIVE_PRODUCT,
            "The Subscription Product must define a non-empty canonical code.",
        )
    return normalized


def _as_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class CommercialValidationError(RuntimeError):
    """A safe commercial validation failure with a runtime reason code."""

    def __init__(
        self,
        reason: ServiceProfileEntitlementReason,
        message: str,
    ) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CommercialContract:
    """Current relational rows forming one exact commercial allocation."""

    profile: Mapping[str, Any]
    subscription: Mapping[str, Any]
    account: Mapping[str, Any]
    price: Mapping[str, Any]
    product: Mapping[str, Any]
    product_code: str
    current_period_start: datetime
    current_period_end: datetime


async def load_commercial_contract(
    rsg: IRelationalStorageGateway,
    *,
    tenant_id: uuid.UUID,
    service_profile_id: uuid.UUID,
    billing_subscription_id: uuid.UUID,
    now: datetime | None = None,
    require_profile_active: bool,
) -> CommercialContract:
    """Load and validate the exact live profile/Subscription/catalog graph."""
    effective_now = _as_utc(now) or datetime.now(timezone.utc)
    profile = await rsg.get_one(
        "service_profile_service_profile",
        {
            "tenant_id": tenant_id,
            "id": service_profile_id,
            "deleted_at": None,
        },
    )
    if (
        profile is None
        or (require_profile_active and profile.get("status") != "active")
        or (
            not require_profile_active
            and profile.get("status") not in {"draft", "active"}
        )
    ):
        raise CommercialValidationError(
            ServiceProfileEntitlementReason.INACTIVE_PROFILE,
            "Service Profile is unavailable for entitlement resolution.",
        )

    subscription = await rsg.get_one(
        "billing_subscription",
        {
            "tenant_id": tenant_id,
            "id": billing_subscription_id,
            "deleted_at": None,
        },
    )
    if subscription is None or subscription.get("status") not in {
        "active",
        "trialing",
    }:
        raise CommercialValidationError(
            ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            "Billing Subscription is not currently eligible.",
        )

    started_at = _as_utc(subscription.get("started_at"))
    period_start = _as_utc(subscription.get("current_period_start"))
    period_end = _as_utc(subscription.get("current_period_end"))
    cancel_at = _as_utc(subscription.get("cancel_at"))
    if (
        started_at is None
        or period_start is None
        or period_end is None
        or started_at > effective_now
        or period_start > effective_now
        or period_end <= effective_now
        or (cancel_at is not None and cancel_at <= effective_now)
        or subscription.get("canceled_at") is not None
        or subscription.get("ended_at") is not None
    ):
        raise CommercialValidationError(
            ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            "Billing Subscription is outside its current eligible period.",
        )

    account = await rsg.get_one(
        "billing_account",
        {
            "tenant_id": tenant_id,
            "id": subscription.get("account_id"),
            "deleted_at": None,
        },
    )
    if account is None:
        raise CommercialValidationError(
            ServiceProfileEntitlementReason.INACTIVE_ACCOUNT,
            "Billing Account is unavailable for entitlement resolution.",
        )

    price = await rsg.get_one(
        "billing_price",
        {"id": subscription.get("price_id"), "deleted_at": None},
    )
    if price is None:
        raise CommercialValidationError(
            ServiceProfileEntitlementReason.INACTIVE_PRICE,
            "Billing Price is unavailable for entitlement resolution.",
        )
    product = await rsg.get_one(
        "billing_product",
        {"id": price.get("product_id"), "deleted_at": None},
    )
    if product is None:
        raise CommercialValidationError(
            ServiceProfileEntitlementReason.INACTIVE_PRODUCT,
            "Billing Product is unavailable for entitlement resolution.",
        )
    product_code = normalize_product_code(product.get("code"))
    return CommercialContract(
        profile=profile,
        subscription=subscription,
        account=account,
        price=price,
        product=product,
        product_code=product_code,
        current_period_start=period_start,
        current_period_end=period_end,
    )
