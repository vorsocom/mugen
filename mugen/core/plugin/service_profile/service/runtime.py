"""Fail-closed runtime Service Profile routing and entitlement services."""

from __future__ import annotations

__all__ = [
    "DefaultServiceProfileEntitlementService",
    "DefaultServiceProfileResolver",
]

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.contract.service.service_profile import (
    IServiceProfileEntitlementService,
    IServiceProfileResolver,
    ServiceProfileEntitlement,
    ServiceProfileEntitlementReason,
    ServiceProfileEntitlementResolution,
    ServiceProfileResolution,
    ServiceProfileResolutionReason,
    ServiceProfileResult,
)
from mugen.core.plugin.service_profile.service.commercial import (
    CommercialValidationError,
    load_commercial_contract,
    normalize_product_code,
)


class DefaultServiceProfileResolver(IServiceProfileResolver):
    """Resolve active profiles from exact live Ingress Binding assignments."""

    def __init__(
        self,
        *,
        rsg: IRelationalStorageGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._rsg = rsg
        self._logging_gateway = logging_gateway

    @staticmethod
    def _fail(reason: ServiceProfileResolutionReason) -> ServiceProfileResolution:
        return ServiceProfileResolution(ok=False, reason_code=reason.value)

    async def resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        ingress_binding_id: uuid.UUID,
    ) -> ServiceProfileResolution:
        """Resolve one active Service Profile or return a safe reason code."""
        try:
            assignments = await self._rsg.find_many(
                "service_profile_ingress_binding",
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "ingress_binding_id": ingress_binding_id,
                            "is_active": True,
                        }
                    )
                ],
                limit=2,
            )
            if not assignments:
                return self._fail(ServiceProfileResolutionReason.MISSING_ASSIGNMENT)
            if len(assignments) != 1:
                return self._fail(ServiceProfileResolutionReason.AMBIGUOUS_ASSIGNMENT)
            binding = await self._rsg.get_one(
                "channel_orchestration_ingress_binding",
                {
                    "tenant_id": tenant_id,
                    "id": ingress_binding_id,
                    "is_active": True,
                },
            )
            if binding is None:
                return self._fail(ServiceProfileResolutionReason.INACTIVE_BINDING)
            profile = await self._rsg.get_one(
                "service_profile_service_profile",
                {
                    "tenant_id": tenant_id,
                    "id": assignments[0].get("service_profile_id"),
                    "status": "active",
                    "deleted_at": None,
                },
            )
            if profile is None:
                return self._fail(ServiceProfileResolutionReason.INACTIVE_PROFILE)
            return ServiceProfileResolution(
                ok=True,
                result=ServiceProfileResult(
                    tenant_id=tenant_id,
                    service_profile_id=uuid.UUID(str(profile["id"])),
                    key=str(profile["key"]),
                    display_name=str(profile["display_name"]),
                ),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "Service Profile ingress resolution failed "
                f"tenant_id={tenant_id} ingress_binding_id={ingress_binding_id} "
                f"error_type={type(exc).__name__}"
            )
            return self._fail(ServiceProfileResolutionReason.RESOLUTION_ERROR)


class DefaultServiceProfileEntitlementService(IServiceProfileEntitlementService):
    """Resolve an exact active allocation and revalidate its Billing graph."""

    def __init__(
        self,
        *,
        rsg: IRelationalStorageGateway,
        logging_gateway: ILoggingGateway,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._rsg = rsg
        self._logging_gateway = logging_gateway
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _fail(
        reason: ServiceProfileEntitlementReason,
    ) -> ServiceProfileEntitlementResolution:
        return ServiceProfileEntitlementResolution(ok=False, reason_code=reason.value)

    async def resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        service_profile_id: uuid.UUID,
        product_code: str,
    ) -> ServiceProfileEntitlementResolution:
        """Resolve exact current entitlement provenance or fail closed."""
        try:
            normalized_code = normalize_product_code(product_code)
            profile = await self._rsg.get_one(
                "service_profile_service_profile",
                {
                    "tenant_id": tenant_id,
                    "id": service_profile_id,
                    "status": "active",
                    "deleted_at": None,
                },
            )
            if profile is None:
                return self._fail(ServiceProfileEntitlementReason.INACTIVE_PROFILE)
            assignments = await self._rsg.find_many(
                "service_profile_subscription",
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "service_profile_id": service_profile_id,
                            "product_code": normalized_code,
                            "status": "active",
                            "deleted_at": None,
                        }
                    )
                ],
                limit=2,
            )
            if not assignments:
                if await self._has_catalog_drift(
                    tenant_id=tenant_id,
                    service_profile_id=service_profile_id,
                    requested_code=normalized_code,
                ):
                    return self._fail(ServiceProfileEntitlementReason.CATALOG_DRIFT)
                return self._fail(ServiceProfileEntitlementReason.MISSING_ASSIGNMENT)
            if len(assignments) != 1:
                return self._fail(ServiceProfileEntitlementReason.AMBIGUOUS_ASSIGNMENT)
            assignment = assignments[0]
            contract = await load_commercial_contract(
                self._rsg,
                tenant_id=tenant_id,
                service_profile_id=service_profile_id,
                billing_subscription_id=uuid.UUID(
                    str(assignment["billing_subscription_id"])
                ),
                now=self._clock(),
                require_profile_active=True,
            )
            stored_code = normalize_product_code(assignment.get("product_code"))
            if stored_code != normalized_code or contract.product_code != stored_code:
                return self._fail(ServiceProfileEntitlementReason.CATALOG_DRIFT)
            return ServiceProfileEntitlementResolution(
                ok=True,
                result=ServiceProfileEntitlement(
                    tenant_id=tenant_id,
                    service_profile_id=service_profile_id,
                    service_profile_subscription_id=uuid.UUID(str(assignment["id"])),
                    billing_account_id=uuid.UUID(str(contract.account["id"])),
                    billing_subscription_id=uuid.UUID(str(contract.subscription["id"])),
                    billing_price_id=uuid.UUID(str(contract.price["id"])),
                    billing_product_id=uuid.UUID(str(contract.product["id"])),
                    product_code=stored_code,
                    subscription_status=str(contract.subscription["status"]),
                    current_period_start=contract.current_period_start,
                    current_period_end=contract.current_period_end,
                ),
            )
        except CommercialValidationError as exc:
            return self._fail(exc.reason)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "Service Profile entitlement resolution failed "
                f"tenant_id={tenant_id} service_profile_id={service_profile_id} "
                f"error_type={type(exc).__name__}"
            )
            return self._fail(ServiceProfileEntitlementReason.RESOLUTION_ERROR)

    async def _has_catalog_drift(
        self,
        *,
        tenant_id: uuid.UUID,
        service_profile_id: uuid.UUID,
        requested_code: str,
    ) -> bool:
        """Detect a renamed Product even when callers use its new live code."""
        assignments = await self._rsg.find_many(
            "service_profile_subscription",
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "service_profile_id": service_profile_id,
                        "status": "active",
                        "deleted_at": None,
                    }
                )
            ],
            limit=1_000,
        )
        for assignment in assignments:
            try:
                contract = await load_commercial_contract(
                    self._rsg,
                    tenant_id=tenant_id,
                    service_profile_id=service_profile_id,
                    billing_subscription_id=uuid.UUID(
                        str(assignment["billing_subscription_id"])
                    ),
                    now=self._clock(),
                    require_profile_active=True,
                )
                stored_code = normalize_product_code(assignment.get("product_code"))
            except (CommercialValidationError, KeyError, TypeError, ValueError):
                continue
            if (
                contract.product_code == requested_code
                and stored_code != requested_code
            ):
                return True
        return False
