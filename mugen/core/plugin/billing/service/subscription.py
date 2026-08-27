"""Provides subscription lifecycle and entitlement provisioning services."""

from __future__ import annotations

__all__ = ["SubscriptionService"]

import calendar
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import uuid

from quart import abort
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
)
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.billing.api.validation import BillingSubscriptionPeriodValidation
from mugen.core.plugin.billing.contract.service.subscription import ISubscriptionService
from mugen.core.plugin.billing.domain import SubscriptionDE


class SubscriptionService(
    IRelationalService[SubscriptionDE],
    ISubscriptionService,
):
    """Manage tenant subscriptions and exact-once period entitlements."""

    _ACTIVE_REFERENCE_TABLES = {
        "run_definition_id": "billing_run_definition",
        "tax_code_id": "billing_tax_code",
        "payment_term_id": "billing_payment_term",
        "invoice_template_id": "billing_invoice_template",
        "discount_definition_id": "billing_discount_definition",
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=SubscriptionDE, table=table, rsg=rsg, **kwargs)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _add_interval(
        cls,
        start: datetime,
        interval_unit: str,
        interval_count: int,
    ) -> datetime:
        start = cls._as_utc(start)
        if interval_unit == "day":
            return start + timedelta(days=interval_count)
        if interval_unit == "week":
            return start + timedelta(weeks=interval_count)
        if interval_unit not in {"month", "year"}:
            abort(409, "Subscription Price has an unsupported billing interval.")
        month_delta = (
            interval_count if interval_unit == "month" else interval_count * 12
        )
        absolute_month = (start.year * 12 + start.month - 1) + month_delta
        year, month_index = divmod(absolute_month, 12)
        month = month_index + 1
        day = min(start.day, calendar.monthrange(year, month)[1])
        return start.replace(year=year, month=month, day=day)

    async def _load_catalog_contract(
        self,
        uow: IRelationalUnitOfWork,
        *,
        tenant_id: uuid.UUID,
        account_id: uuid.UUID,
        price_id: uuid.UUID,
        references: Mapping[str, Any],
        status_code: int,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        account = await uow.get_one(
            "billing_account",
            {"id": account_id, "tenant_id": tenant_id, "deleted_at": None},
        )
        if account is None:
            abort(
                status_code,
                "AccountId must reference an available account owned by the "
                "route tenant.",
            )
        price = await uow.get_one(
            "billing_price",
            {"id": price_id, "deleted_at": None},
        )
        if price is None:
            abort(status_code, "PriceId must reference an available global Price.")
        product = await uow.get_one(
            "billing_product",
            {"id": price["product_id"], "deleted_at": None},
        )
        if product is None:
            abort(status_code, "The selected Price's Product is not available.")
        if price.get("price_type") != "recurring":
            abort(status_code, "Subscriptions require a recurring package Price.")
        if not price.get("interval_unit") or not price.get("interval_count"):
            abort(status_code, "Recurring Price must define a complete interval.")
        for field_name, table_name in self._ACTIVE_REFERENCE_TABLES.items():
            reference_id = references.get(field_name)
            if reference_id is None:
                continue
            definition = await uow.get_one(table_name, {"id": reference_id})
            if definition is None or not definition.get("is_active"):
                label = "".join(part.title() for part in field_name.split("_"))
                abort(status_code, f"{label} must reference an active definition.")
        return price, account

    @classmethod
    def _period_for_create(
        cls,
        payload: dict[str, Any],
        price: Mapping[str, Any],
    ) -> tuple[datetime, datetime]:
        started_at = cls._as_utc(
            payload.get("started_at") or datetime.now(timezone.utc)
        )
        payload["started_at"] = started_at
        start = payload.get("current_period_start")
        end = payload.get("current_period_end")
        if start is None:
            start = started_at
            end = cls._add_interval(
                start,
                str(price["interval_unit"]),
                int(price["interval_count"]),
            )
        else:
            start = cls._as_utc(start)
            end = cls._as_utc(end)
        if end <= start:
            abort(400, "CurrentPeriodEnd must be later than CurrentPeriodStart.")
        payload["current_period_start"] = start
        payload["current_period_end"] = end
        return start, end

    async def _provision_buckets(
        self,
        uow: IRelationalUnitOfWork,
        *,
        subscription: Mapping[str, Any],
        period_start: datetime,
        period_end: datetime,
        generation_source: str,
        billing_run_id: uuid.UUID | None = None,
    ) -> int:
        rules = await uow.find(
            "billing_price_entitlement",
            filter_groups=[
                FilterGroup(
                    where={
                        "price_id": subscription["price_id"],
                        "deleted_at": None,
                    }
                )
            ],
        )
        generated = 0
        for rule in rules:
            meter = await uow.get_one(
                "billing_meter_definition",
                {"id": rule["meter_definition_id"]},
            )
            if meter is None or not meter.get("is_active"):
                abort(409, "Entitlement rule references an inactive meter definition.")
            identity = {
                "tenant_id": subscription["tenant_id"],
                "account_id": subscription["account_id"],
                "subscription_id": subscription["id"],
                "price_entitlement_id": rule["id"],
                "period_start": period_start,
                "period_end": period_end,
            }
            existing = await uow.get_one("billing_entitlement_bucket", identity)
            if existing is not None:
                compatible = (
                    existing.get("price_id") == subscription["price_id"]
                    and existing.get("meter_definition_id") == meter["id"]
                    and int(existing.get("included_quantity") or 0)
                    == int(rule["included_quantity"])
                )
                if not compatible:
                    abort(409, "Existing entitlement bucket conflicts with Price rule.")
                continue
            legacy_rows = await uow.find(
                "billing_entitlement_bucket",
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": subscription["tenant_id"],
                            "account_id": subscription["account_id"],
                            "subscription_id": subscription["id"],
                            "price_id": subscription["price_id"],
                            "meter_code": meter["code"],
                            "period_start": period_start,
                            "period_end": period_end,
                            "price_entitlement_id": None,
                        }
                    )
                ],
                limit=2,
            )
            if legacy_rows:
                if len(legacy_rows) != 1:
                    abort(409, "Multiple legacy buckets conflict with Price rule.")
                legacy = legacy_rows[0]
                if int(legacy.get("included_quantity") or 0) != int(
                    rule["included_quantity"]
                ):
                    abort(409, "Legacy bucket allowance conflicts with Price rule.")
                await uow.update_one(
                    "billing_entitlement_bucket",
                    {"tenant_id": subscription["tenant_id"], "id": legacy["id"]},
                    {
                        "price_entitlement_id": rule["id"],
                        "meter_definition_id": meter["id"],
                        "billing_run_id": billing_run_id,
                        "generation_source": generation_source,
                    },
                )
                generated += 1
                continue
            await uow.insert(
                "billing_entitlement_bucket",
                {
                    **identity,
                    "price_id": subscription["price_id"],
                    "meter_definition_id": meter["id"],
                    "billing_run_id": billing_run_id,
                    "meter_code": meter["code"],
                    "included_quantity": int(rule["included_quantity"]),
                    "consumed_quantity": 0,
                    "rollover_quantity": 0,
                    "adjustment_quantity": 0,
                    "generation_source": generation_source,
                    "attributes": {
                        "rollover_policy": rule.get("rollover_policy") or "none"
                    },
                },
            )
            generated += 1
        return generated

    async def create(self, values: Mapping[str, Any]) -> SubscriptionDE:
        payload = dict(values)
        try:
            async with self._rsg.unit_of_work() as uow:
                price, account = await self._load_catalog_contract(
                    uow,
                    tenant_id=payload["tenant_id"],
                    account_id=payload["account_id"],
                    price_id=payload["price_id"],
                    references=payload,
                    status_code=400,
                )
                for field_name in (
                    "tax_code_id",
                    "payment_term_id",
                    "invoice_template_id",
                    "discount_definition_id",
                ):
                    if (
                        payload.get(field_name) is None
                        and account.get(field_name) is not None
                    ):
                        payload[field_name] = account[field_name]
                period_start, period_end = self._period_for_create(payload, price)
                inserted = await uow.insert(self.table, payload)
                if inserted is None:
                    abort(500)
                await self._provision_buckets(
                    uow,
                    subscription=inserted,
                    period_start=period_start,
                    period_end=period_end,
                    generation_source="subscription_activation",
                )
        except IntegrityError:
            abort(
                409, "Subscription or entitlement period conflicts with existing data."
            )
        except SQLAlchemyError:
            abort(500)
        return self._from_record(inserted)

    async def _validate_reference_changes(
        self,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = dict(changes)
        for field_name, table_name in self._ACTIVE_REFERENCE_TABLES.items():
            reference_id = payload.get(field_name)
            if reference_id is None:
                continue
            definition = await self._rsg.get_one(table_name, {"id": reference_id})
            if definition is None or not definition.get("is_active"):
                label = "".join(part.title() for part in field_name.split("_"))
                abort(400, f"{label} must reference an active definition.")
        return payload

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> SubscriptionDE | None:
        return await super().update(
            where,
            await self._validate_reference_changes(changes),
        )

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> SubscriptionDE | None:
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=await self._validate_reference_changes(changes),
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> SubscriptionDE:
        try:
            current = await self.get(
                {**dict(where), "row_version": expected_row_version}
            )
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
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Cancel an active, trialing, or paused Subscription."""
        current = await self._get_for_action(
            where=where,
            expected_row_version=int(data.row_version),
        )
        if current.status not in {"active", "trialing", "paused"}:
            abort(409, "Subscription can only be canceled from active/trialing/paused.")
        try:
            updated = await self.update_with_row_version(
                where,
                expected_row_version=int(data.row_version),
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
            abort(404, "Subscription not found.")
        return "", 204

    async def action_reactivate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Reactivate a Subscription and reconcile its current period."""
        try:
            async with self._rsg.unit_of_work() as uow:
                current = await uow.get_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                )
                if current is None:
                    if await uow.get_one(self.table, dict(where)) is None:
                        abort(404, "Subscription not found.")
                    abort(409, "RowVersion conflict. Refresh and retry.")
                if current["status"] not in {"canceled", "paused"}:
                    abort(
                        409,
                        "Subscription can only be reactivated from canceled/paused.",
                    )
                await self._load_catalog_contract(
                    uow,
                    tenant_id=tenant_id,
                    account_id=current["account_id"],
                    price_id=current["price_id"],
                    references=current,
                    status_code=409,
                )
                updated = await uow.update_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                    {
                        "status": "active",
                        "cancel_at": None,
                        "canceled_at": None,
                        "ended_at": None,
                    },
                )
                if updated is None:
                    abort(409, "RowVersion conflict. Refresh and retry.")
                await self._provision_buckets(
                    uow,
                    subscription=updated,
                    period_start=updated["current_period_start"],
                    period_end=updated["current_period_end"],
                    generation_source="reconciliation",
                )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except IntegrityError:
            abort(409, "Entitlement period conflicts with existing data.")
        except SQLAlchemyError:
            abort(500)
        return "", 204

    async def action_advance_period(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: BillingSubscriptionPeriodValidation,
    ) -> tuple[dict[str, Any], int]:
        """Advance to the next contiguous period and provision its buckets."""
        try:
            async with self._rsg.unit_of_work() as uow:
                current = await uow.get_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                )
                if current is None:
                    if await uow.get_one(self.table, dict(where)) is None:
                        abort(404, "Subscription not found.")
                    abort(409, "RowVersion conflict. Refresh and retry.")
                if current["status"] not in {"active", "trialing"}:
                    abort(409, "Only active or trialing Subscriptions may advance.")
                price = await uow.get_one(
                    "billing_price",
                    {"id": current["price_id"], "deleted_at": None},
                )
                if price is None:
                    abort(409, "Subscription Price is unavailable.")
                start = (
                    self._as_utc(data.period_start)
                    if data.period_start is not None
                    else current["current_period_end"]
                )
                if start != current["current_period_end"]:
                    abort(409, "The next period must start at CurrentPeriodEnd.")
                end = (
                    self._as_utc(data.period_end)
                    if data.period_end is not None
                    else self._add_interval(
                        start,
                        str(price["interval_unit"]),
                        int(price["interval_count"]),
                    )
                )
                updated = await uow.update_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                    {"current_period_start": start, "current_period_end": end},
                )
                if updated is None:
                    abort(409, "RowVersion conflict. Refresh and retry.")
                await self._provision_buckets(
                    uow,
                    subscription=updated,
                    period_start=start,
                    period_end=end,
                    generation_source="period_advance",
                )
        except (IntegrityError, RowVersionConflict):
            abort(409, "Duplicate entitlement period or stale Subscription.")
        except SQLAlchemyError:
            abort(500)
        return "", 204

    async def action_reconcile_entitlements(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: BillingSubscriptionPeriodValidation,
    ) -> tuple[dict[str, Any], int]:
        """Idempotently restore genuinely missing current-period buckets."""
        if data.period_start is not None or data.period_end is not None:
            abort(400, "Reconciliation uses the Subscription's current period.")
        try:
            async with self._rsg.unit_of_work() as uow:
                current = await uow.get_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                )
                if current is None:
                    if await uow.get_one(self.table, dict(where)) is None:
                        abort(404, "Subscription not found.")
                    abort(409, "RowVersion conflict. Refresh and retry.")
                if current["status"] not in {"active", "trialing", "paused"}:
                    abort(409, "Canceled or ended Subscriptions cannot be reconciled.")
                await self._provision_buckets(
                    uow,
                    subscription=current,
                    period_start=current["current_period_start"],
                    period_end=current["current_period_end"],
                    generation_source="reconciliation",
                )
                await uow.update_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                    {"current_period_start": current["current_period_start"]},
                )
        except (IntegrityError, RowVersionConflict):
            abort(409, "Duplicate entitlement period or stale Subscription.")
        except SQLAlchemyError:
            abort(500)
        return "", 204
