"""Provides a CRUD service for billing prices."""

__all__ = ["PriceService"]

from datetime import datetime, timezone
from typing import Any, Mapping
import uuid

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict

from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.billing.contract.service.price import IPriceService
from mugen.core.plugin.billing.domain import PriceDE
from mugen.core.plugin.billing.service.product import ProductService


class PriceService(  # pylint: disable=too-few-public-methods
    IRelationalService[PriceDE],
    IPriceService,
):
    """A CRUD service for billing prices."""

    _PRODUCT_TABLE = "billing_product"
    _REFERENCE_TABLES = (
        "billing_subscription",
        "billing_invoice_line",
        "billing_usage_event",
        "billing_entitlement_bucket",
        "ops_metering_usage_session",
        "ops_metering_usage_record",
        "ops_metering_rated_usage",
    )
    _COMMERCIAL_FIELDS = frozenset(
        {
            "product_id",
            "price_type",
            "currency_definition_id",
            "meter_definition_id",
            "unit_amount",
            "interval_unit",
            "interval_count",
            "trial_period_days",
        }
    )

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        self._product_service = ProductService(
            table=self._PRODUCT_TABLE,
            rsg=rsg,
        )
        super().__init__(
            de_type=PriceDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def _normalize_changes(values: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(values)
        for field_name in (
            "code",
            "price_type",
            "interval_unit",
        ):
            value = payload.get(field_name)
            if isinstance(value, str):
                normalized = value.strip()
                if field_name in {"price_type", "interval_unit"}:
                    normalized = normalized.lower()
                payload[field_name] = normalized
        return payload

    async def _validate_product(self, product_id: uuid.UUID) -> None:
        product = await self._product_service.get(
            {
                "id": product_id,
                "deleted_at": None,
            }
        )
        if product is None:
            abort(400, "ProductId must reference an available global Product.")

    async def _apply_reference_contract(self, values: dict[str, Any]) -> None:
        currency = await self._rsg.get_one(
            "billing_currency_definition",
            {"id": values["currency_definition_id"]},
        )
        if currency is None or not currency.get("is_active"):
            abort(400, "CurrencyDefinitionId must reference an active currency.")
        values["currency"] = str(currency["code"]).upper()

        meter_id = values.get("meter_definition_id")
        if values.get("price_type") == "metered":
            if meter_id is None:
                abort(400, "Metered Prices require MeterDefinitionId.")
            meter = await self._rsg.get_one(
                "billing_meter_definition",
                {"id": meter_id},
            )
            if meter is None or not meter.get("is_active"):
                abort(400, "MeterDefinitionId must reference an active meter.")
            values["meter_code"] = meter["code"]
            values["usage_unit"] = meter["unit"]
            return

        if meter_id is not None:
            abort(400, "Unmetered Prices must omit MeterDefinitionId.")
        values["meter_code"] = None
        values["usage_unit"] = None

    async def _is_referenced(self, price_id: uuid.UUID) -> bool:
        for table_name in self._REFERENCE_TABLES:
            count = await self._rsg.count_many(
                table_name,
                filter_groups=[FilterGroup(where={"price_id": price_id})],
            )
            if count > 0:
                return True
        return False

    async def _validate_update(
        self,
        current: PriceDE,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = self._normalize_changes(changes)
        effective = {
            field_name: getattr(current, field_name)
            for field_name in (
                "product_id",
                "price_type",
                "currency_definition_id",
                "meter_definition_id",
                "currency",
                "unit_amount",
                "interval_unit",
                "interval_count",
                "trial_period_days",
                "usage_unit",
                "meter_code",
            )
        }
        effective.update(payload)

        commercial_changes = {
            field_name
            for field_name in self._COMMERCIAL_FIELDS.intersection(payload)
            if payload[field_name] != getattr(current, field_name)
        }
        if commercial_changes and current.id is not None:
            if await self._is_referenced(current.id):
                abort(
                    409,
                    "Referenced Prices cannot change commercial fields; create "
                    "a new Price.",
                )

        if "product_id" in commercial_changes:
            await self._validate_product(effective["product_id"])
        if commercial_changes.intersection(
            {"currency_definition_id", "meter_definition_id", "price_type"}
        ):
            await self._apply_reference_contract(effective)
            payload["currency"] = effective["currency"]
            payload["meter_code"] = effective["meter_code"]
            payload["usage_unit"] = effective["usage_unit"]
        return payload

    async def create(self, values: Mapping[str, Any]) -> PriceDE:
        payload = self._normalize_changes(values)
        await self._validate_product(payload["product_id"])
        await self._apply_reference_contract(payload)
        return await super().create(payload)

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> PriceDE | None:
        current = await self.get(where)
        if current is None:
            return None
        payload = await self._validate_update(current, changes)
        return await super().update(where, payload)

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> PriceDE | None:
        current = await self.get(where)
        if current is None:
            return None
        payload = await self._validate_update(current, changes)
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=payload,
        )

    async def entity_action_archive(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Soft-delete a global Price without disturbing historical references."""
        try:
            current = await self.get({"id": entity_id})
        except SQLAlchemyError:
            abort(500)

        if current is None:
            abort(404, "Price not found.")
        if current.deleted_at is not None:
            return "", 204

        try:
            updated = await self.update_with_row_version(
                {"id": entity_id},
                expected_row_version=int(data.row_version),
                changes={
                    "deleted_at": datetime.now(timezone.utc),
                    "deleted_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Archive not performed. No row matched.")
        return "", 204
