"""Provides a CRUD service for billing subscriptions (plus common lifecycle actions)."""

__all__ = ["SubscriptionService"]

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
from mugen.core.plugin.billing.service.account import AccountService
from mugen.core.plugin.billing.service.price import PriceService
from mugen.core.plugin.billing.service.product import ProductService
from mugen.core.plugin.billing.contract.service.subscription import ISubscriptionService
from mugen.core.plugin.billing.domain import SubscriptionDE
from mugen.core.plugin.ops_metering.service.meter_definition import (
    MeterDefinitionService,
)


class SubscriptionService(
    IRelationalService[SubscriptionDE],
    ISubscriptionService,
):
    """A CRUD service for billing subscriptions."""

    _ACCOUNT_TABLE = "billing_account"
    _PRICE_TABLE = "billing_price"
    _PRODUCT_TABLE = "billing_product"
    _METER_DEFINITION_TABLE = "ops_metering_meter_definition"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        self._account_service = AccountService(
            table=self._ACCOUNT_TABLE,
            rsg=rsg,
        )
        self._price_service = PriceService(
            table=self._PRICE_TABLE,
            rsg=rsg,
        )
        self._product_service = ProductService(
            table=self._PRODUCT_TABLE,
            rsg=rsg,
        )
        self._meter_definition_service = MeterDefinitionService(
            table=self._METER_DEFINITION_TABLE,
            rsg=rsg,
        )
        super().__init__(
            de_type=SubscriptionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _validate_catalog_selection(
        self,
        *,
        tenant_id: uuid.UUID,
        account_id: uuid.UUID,
        price_id: uuid.UUID,
        status_code: int,
    ) -> None:
        account = await self._account_service.get(
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "deleted_at": None,
            }
        )
        if account is None:
            abort(
                status_code,
                "AccountId must reference an available Billing Account owned by "
                "the route tenant.",
            )

        price = await self._price_service.get(
            {
                "id": price_id,
                "deleted_at": None,
            }
        )
        if price is None:
            abort(status_code, "PriceId must reference an available global Price.")

        product = await self._product_service.get(
            {
                "id": price.product_id,
                "deleted_at": None,
            }
        )
        if product is None:
            abort(status_code, "The selected Price's Product is not available.")

        if price.meter_code is None:
            return

        meter_code = price.meter_code.strip()
        active_definitions = await self._meter_definition_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "is_active": True,
                    }
                )
            ]
        )
        matching_definitions = [
            definition
            for definition in active_definitions
            if (definition.code or "").strip().casefold() == meter_code.casefold()
        ]
        if not matching_definitions:
            abort(
                status_code,
                "Metered Price requires a matching active tenant Meter Definition.",
            )
        if len(matching_definitions) > 1:
            abort(
                status_code,
                "Metered Price matches multiple normalized tenant Meter Definitions.",
            )

        meter_definition = matching_definitions[0]
        definition_unit = (meter_definition.unit or "").strip().casefold()
        price_unit = (price.usage_unit or "").strip().casefold()
        if definition_unit != price_unit:
            abort(
                status_code,
                "Meter Definition unit must match the Price UsageUnit.",
            )

    async def create(self, values: Mapping[str, Any]) -> SubscriptionDE:
        payload = dict(values)
        await self._validate_catalog_selection(
            tenant_id=payload["tenant_id"],
            account_id=payload["account_id"],
            price_id=payload["price_id"],
            status_code=400,
        )
        return await super().create(payload)

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> SubscriptionDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version
        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Subscription not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def action_cancel(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Cancel a subscription (entity action)."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status not in {"active", "trialing", "paused"}:
            abort(409, "Subscription can only be canceled from active/trialing/paused.")

        svc: ICrudServiceWithRowVersion[SubscriptionDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "canceled",
                    "canceled_at": datetime.now(timezone.utc),
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204

    async def action_reactivate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Reactivate a canceled/paused subscription (entity action)."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status not in {"canceled", "paused"}:
            abort(409, "Subscription can only be reactivated from canceled/paused.")

        await self._validate_catalog_selection(
            tenant_id=tenant_id,
            account_id=current.account_id,
            price_id=current.price_id,
            status_code=409,
        )

        svc: ICrudServiceWithRowVersion[SubscriptionDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "active",
                    "cancel_at": None,
                    "canceled_at": None,
                    "ended_at": None,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204
