"""Provides Service Profile Subscription allocation lifecycle behavior."""

from __future__ import annotations

__all__ = ["ServiceProfileSubscriptionService"]

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
)
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.service_profile.contract.service import (
    IServiceProfileSubscriptionService,
)
from mugen.core.plugin.service_profile.domain import ServiceProfileSubscriptionDE
from mugen.core.plugin.service_profile.service.commercial import (
    CommercialValidationError,
    load_commercial_contract,
)


class ServiceProfileSubscriptionService(
    IRelationalService[ServiceProfileSubscriptionDE],
    IServiceProfileSubscriptionService,
):
    """Manage exact commercial allocation lifecycle transitions."""

    _PROFILE_TABLE = "service_profile_service_profile"
    _SUBSCRIPTION_TABLE = "billing_subscription"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ServiceProfileSubscriptionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    async def create(
        self,
        values: Mapping[str, Any],
    ) -> ServiceProfileSubscriptionDE:
        """Create a draft assignment without deriving catalog state yet."""
        payload = dict(values)
        payload.pop("product_code", None)
        payload.update(
            {
                "status": "draft",
                "product_code": None,
                "activated_at": None,
                "disabled_at": None,
            }
        )
        try:
            profile = await self._rsg.get_one(
                self._PROFILE_TABLE,
                {
                    "tenant_id": payload.get("tenant_id"),
                    "id": payload.get("service_profile_id"),
                    "deleted_at": None,
                },
            )
            subscription = await self._rsg.get_one(
                self._SUBSCRIPTION_TABLE,
                {
                    "tenant_id": payload.get("tenant_id"),
                    "id": payload.get("billing_subscription_id"),
                    "deleted_at": None,
                },
            )
        except SQLAlchemyError:
            abort(500)
        if profile is None or profile.get("status") == "disabled":
            abort(
                400,
                "ServiceProfileId must reference an available route-tenant profile.",
            )
        if subscription is None:
            abort(
                400,
                "BillingSubscriptionId must reference an available route-tenant "
                "Subscription.",
            )
        return await super().create(payload)

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> ServiceProfileSubscriptionDE:
        try:
            current = await self.get(
                {**dict(where), "row_version": expected_row_version}
            )
            if current is not None and current.deleted_at is None:
                return current
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)
        if base is None or base.deleted_at is not None:
            abort(404, "Service Profile Subscription assignment not found.")
        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> tuple[dict[str, Any], int]:
        service: ICrudServiceWithRowVersion[ServiceProfileSubscriptionDE] = self
        try:
            updated = await service.update_with_row_version(
                where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)
        if updated is None:
            abort(404, "Service Profile Subscription assignment not found.")
        return "", 204

    async def _assert_allocation_available(
        self,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        service_profile_id: uuid.UUID,
        billing_subscription_id: uuid.UUID,
        product_code: str,
    ) -> None:
        subscription_rows = await self._rsg.find_many(
            self.table,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "billing_subscription_id": billing_subscription_id,
                        "status": "active",
                        "deleted_at": None,
                    }
                )
            ],
            limit=2,
        )
        profile_rows = await self._rsg.find_many(
            self.table,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "service_profile_id": service_profile_id,
                        "product_code": product_code,
                        "status": "active",
                        "deleted_at": None,
                    }
                )
            ],
            limit=2,
        )
        if any(row.get("id") != assignment_id for row in subscription_rows):
            abort(409, "Billing Subscription is already actively assigned.")
        if any(row.get("id") != assignment_id for row in profile_rows):
            abort(409, "Service Profile already has an active assignment for Product.")

    async def action_activate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Validate and activate one exact commercial allocation."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != "draft":
            abort(409, "Only draft Subscription assignments can be activated.")
        if (
            current.service_profile_id is None
            or current.billing_subscription_id is None
        ):
            abort(409, "Subscription assignment identity is incomplete.")
        try:
            contract = await load_commercial_contract(
                self._rsg,
                tenant_id=tenant_id,
                service_profile_id=current.service_profile_id,
                billing_subscription_id=current.billing_subscription_id,
                require_profile_active=False,
            )
            await self._assert_allocation_available(
                tenant_id=tenant_id,
                assignment_id=entity_id,
                service_profile_id=current.service_profile_id,
                billing_subscription_id=current.billing_subscription_id,
                product_code=contract.product_code,
            )
        except CommercialValidationError as exc:
            abort(409, str(exc))
        except SQLAlchemyError:
            abort(500)
        return await self._update_action(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "active",
                "product_code": contract.product_code,
                "activated_at": self._now_utc(),
                "disabled_at": None,
            },
        )

    async def action_disable(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Disable an active assignment while retaining its Product snapshot."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != "active":
            abort(409, "Only active Subscription assignments can be disabled.")
        return await self._update_action(
            where=where,
            expected_row_version=expected_row_version,
            changes={"status": "disabled", "disabled_at": self._now_utc()},
        )
