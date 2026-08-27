"""Integration-style unit tests for normalized billing ownership workflows."""

from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
import unittest
import uuid
from unittest.mock import patch

from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.billing.api.validation import (
    BillingEntitlementAdjustValidation,
    BillingRunFailValidation,
    BillingRunRetryValidation,
    BillingSubscriptionPeriodValidation,
)
from mugen.core.plugin.billing.service import billing_run as billing_run_mod
from mugen.core.plugin.billing.service import catalog as catalog_mod
from mugen.core.plugin.billing.service import entitlement_bucket as bucket_mod
from mugen.core.plugin.billing.service.billing_run import BillingRunService
from mugen.core.plugin.billing.service.catalog import (
    CurrencyDefinitionService,
    DiscountDefinitionService,
    InvoiceTemplateService,
    MeterDefinitionService,
    PaymentTermService,
    PriceEntitlementService,
    RunDefinitionService,
    TaxCodeService,
    TaxRateService,
)
from mugen.core.plugin.billing.service.entitlement_bucket import (
    EntitlementBucketService,
)
from mugen.core.plugin.billing.service.invoice import InvoiceService
from mugen.core.plugin.billing.service.subscription import SubscriptionService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None, **_kwargs):
    raise _AbortCalled(code, message)


class _MemoryGateway:
    """Small transactional relational fake with DNF equality filtering."""

    def __init__(self):
        self.rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    @staticmethod
    def _matches(row: Mapping[str, Any], where: Mapping[str, Any]) -> bool:
        return all(row.get(key) == value for key, value in where.items())

    @staticmethod
    def _project(
        row: Mapping[str, Any], columns: Sequence[str] | None
    ) -> dict[str, Any]:
        if columns is None:
            return dict(row)
        return {column: row.get(column) for column in columns}

    @asynccontextmanager
    async def unit_of_work(self):
        yield self

    async def insert(
        self,
        table: str,
        record: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> dict[str, Any] | None:
        row = dict(record)
        row.setdefault("id", uuid.uuid4())
        row.setdefault("row_version", 1)
        row.setdefault("created_at", datetime.now(timezone.utc))
        row.setdefault("updated_at", row["created_at"])
        row.setdefault("deleted_at", None)
        if table == "billing_subscription":
            row.setdefault("status", "active")
        if table in {
            "billing_meter_definition",
            "billing_run_definition",
            "billing_tax_code",
            "billing_tax_rate",
            "billing_payment_term",
            "billing_invoice_template",
            "billing_discount_definition",
        }:
            row.setdefault("is_active", True)
        self.rows[table].append(row)
        return dict(row) if returning else None

    async def insert_one(self, table: str, record: Mapping[str, Any]) -> dict[str, Any]:
        result = await self.insert(table, record)
        assert result is not None
        return result

    async def get_one(
        self,
        table: str,
        where: Mapping[str, Any],
        *,
        columns: Sequence[str] | None = None,
    ) -> dict[str, Any] | None:
        for row in self.rows[table]:
            if self._matches(row, where):
                return self._project(row, columns)
        return None

    async def find(
        self,
        table: str,
        *,
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by=None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        del order_by
        candidates = self.rows[table]
        if filter_groups:
            candidates = [
                row
                for row in candidates
                if any(self._matches(row, group.where) for group in filter_groups)
            ]
        start = offset or 0
        stop = None if limit is None else start + limit
        return [self._project(row, columns) for row in candidates[start:stop]]

    async def find_many(self, table: str, **kwargs) -> list[dict[str, Any]]:
        return await self.find(table, **kwargs)

    async def count(
        self,
        table: str,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
    ) -> int:
        return len(await self.find(table, filter_groups=filter_groups))

    async def count_many(
        self,
        table: str,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
    ) -> int:
        return await self.count(table, filter_groups=filter_groups)

    async def update_one(
        self,
        table: str,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> dict[str, Any] | None:
        for row in self.rows[table]:
            if self._matches(row, where):
                row.update(changes)
                row["row_version"] = int(row.get("row_version") or 0) + 1
                row["updated_at"] = datetime.now(timezone.utc)
                return dict(row) if returning else None
        return None

    async def delete_one(
        self, table: str, where: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        for index, row in enumerate(self.rows[table]):
            if self._matches(row, where):
                return dict(self.rows[table].pop(index))
        return None


class TestNormalizedBillingWorkflows(unittest.IsolatedAsyncioTestCase):
    """Exercise shared global definitions and tenant operational state together."""

    async def asyncSetUp(self) -> None:
        self.rsg = _MemoryGateway()
        self.currency_id = uuid.uuid4()
        self.product_id = uuid.uuid4()
        self.price_id = uuid.uuid4()
        self.meter_ids = (uuid.uuid4(), uuid.uuid4())
        await self.rsg.insert_one(
            "billing_currency_definition",
            {
                "id": self.currency_id,
                "code": "GYD",
                "is_active": True,
            },
        )
        await self.rsg.insert_one(
            "billing_product",
            {"id": self.product_id, "code": "inbox", "deleted_at": None},
        )
        await self.rsg.insert_one(
            "billing_price",
            {
                "id": self.price_id,
                "product_id": self.product_id,
                "price_type": "recurring",
                "currency_definition_id": self.currency_id,
                "interval_unit": "month",
                "interval_count": 1,
                "deleted_at": None,
            },
        )
        for meter_id, code, unit in (
            (
                self.meter_ids[0],
                "example.usage.minutes",
                "minute",
            ),
            (
                self.meter_ids[1],
                "example.usage.tasks",
                "task",
            ),
        ):
            await self.rsg.insert_one(
                "billing_meter_definition",
                {
                    "id": meter_id,
                    "code": code,
                    "unit": unit,
                    "aggregation_mode": "sum",
                    "is_active": True,
                },
            )
        for meter_id, quantity in zip(self.meter_ids, (150, 2)):
            await self.rsg.insert_one(
                "billing_price_entitlement",
                {
                    "price_id": self.price_id,
                    "meter_definition_id": meter_id,
                    "included_quantity": quantity,
                    "rollover_policy": "none",
                    "deleted_at": None,
                },
            )

    async def _create_account(self, tenant_id: uuid.UUID) -> dict[str, Any]:
        return await self.rsg.insert_one(
            "billing_account",
            {
                "tenant_id": tenant_id,
                "code": str(uuid.uuid4()),
                "currency_definition_id": self.currency_id,
                "deleted_at": None,
            },
        )

    async def _create_subscription(
        self,
        tenant_id: uuid.UUID,
        account_id: uuid.UUID,
        start: datetime,
        end: datetime | None = None,
        **references,
    ):
        values = {
            "tenant_id": tenant_id,
            "account_id": account_id,
            "price_id": self.price_id,
            "started_at": start,
            **references,
        }
        if end is not None:
            values.update(
                current_period_start=start,
                current_period_end=end,
            )
        return await SubscriptionService(
            table="billing_subscription",
            rsg=self.rsg,
        ).create(values)

    async def test_shared_catalog_provisions_exactly_once_for_two_tenants(self) -> None:
        service = SubscriptionService(
            table="billing_subscription",
            rsg=self.rsg,
        )
        tenant_ids = (uuid.uuid4(), uuid.uuid4())
        account_1 = await self._create_account(tenant_ids[0])
        account_2 = await self._create_account(tenant_ids[1])
        start = datetime(2026, 1, 31, tzinfo=timezone.utc)

        first = await self._create_subscription(tenant_ids[0], account_1["id"], start)
        second = await self._create_subscription(tenant_ids[1], account_2["id"], start)

        self.assertEqual(first.current_period_end.day, 28)
        self.assertEqual(second.current_period_end.day, 28)
        self.assertEqual(len(self.rsg.rows["billing_meter_definition"]), 2)
        self.assertEqual(len(self.rsg.rows["billing_entitlement_bucket"]), 4)
        self.assertEqual(
            sorted(
                row["included_quantity"]
                for row in self.rsg.rows["billing_entitlement_bucket"]
            ),
            [2, 2, 150, 150],
        )
        self.assertTrue(
            all(
                row["price_entitlement_id"] is not None
                and row["meter_definition_id"] in self.meter_ids
                and row["generation_source"] == "subscription_activation"
                for row in self.rsg.rows["billing_entitlement_bucket"]
            )
        )

        where = {"tenant_id": tenant_ids[0], "id": first.id}
        result = await service.action_reconcile_entitlements(
            tenant_id=tenant_ids[0],
            entity_id=first.id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=BillingSubscriptionPeriodValidation(row_version=1),
        )
        self.assertEqual(result, ("", 204))
        self.assertEqual(len(self.rsg.rows["billing_entitlement_bucket"]), 4)

        result = await service.action_advance_period(
            tenant_id=tenant_ids[0],
            entity_id=first.id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=BillingSubscriptionPeriodValidation(row_version=2),
        )
        self.assertEqual(result, ("", 204))
        self.assertEqual(len(self.rsg.rows["billing_entitlement_bucket"]), 6)
        historical = [
            row
            for row in self.rsg.rows["billing_entitlement_bucket"]
            if row["tenant_id"] == tenant_ids[0] and row["period_start"] == start
        ]
        self.assertEqual(
            sorted(row["included_quantity"] for row in historical), [2, 150]
        )

    async def test_audited_adjustments_are_guarded_and_idempotent(self) -> None:
        tenant_id = uuid.uuid4()
        account = await self._create_account(tenant_id)
        subscription = await self._create_subscription(
            tenant_id,
            account["id"],
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        bucket = self.rsg.rows["billing_entitlement_bucket"][0]
        service = EntitlementBucketService(
            table="billing_entitlement_bucket",
            rsg=self.rsg,
        )
        data = BillingEntitlementAdjustValidation(
            row_version=bucket["row_version"],
            quantity_delta=10,
            reason="Support correction",
            idempotency_key="support-1",
        )
        common = {
            "tenant_id": tenant_id,
            "entity_id": bucket["id"],
            "where": {"tenant_id": tenant_id, "id": bucket["id"]},
            "auth_user_id": uuid.uuid4(),
            "data": data,
        }
        self.assertEqual(await service.action_adjust(**common), ("", 204))
        self.assertEqual(await service.action_adjust(**common), ("", 204))
        self.assertEqual(bucket["adjustment_quantity"], 10)
        self.assertEqual(len(self.rsg.rows["billing_entitlement_adjustment"]), 1)
        adjustment = self.rsg.rows["billing_entitlement_adjustment"][0]
        self.assertEqual(adjustment["subscription_id"], subscription.id)
        self.assertEqual(adjustment["capacity_after"], 160)

        with patch.object(bucket_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.action_adjust(
                    **{
                        **common,
                        "data": BillingEntitlementAdjustValidation(
                            row_version=bucket["row_version"],
                            quantity_delta=-1000,
                            reason="Invalid reduction",
                            idempotency_key="support-2",
                        ),
                    }
                )
        self.assertEqual(ex.exception.code, 409)

    async def test_billing_runs_advance_periods_and_record_retries(self) -> None:
        tenant_id = uuid.uuid4()
        account = await self._create_account(tenant_id)
        definition = await self.rsg.insert_one(
            "billing_run_definition",
            {
                "code": "monthly-standard",
                "frequency": "monthly",
                "interval_count": 1,
                "timezone": "America/Guyana",
                "is_active": True,
            },
        )
        december = datetime(2025, 12, 1, 4, tzinfo=timezone.utc)
        january = datetime(2026, 1, 1, 4, tzinfo=timezone.utc)
        february = datetime(2026, 2, 1, 4, tzinfo=timezone.utc)
        march = datetime(2026, 3, 1, 4, tzinfo=timezone.utc)
        subscription = await self._create_subscription(
            tenant_id,
            account["id"],
            december,
            january,
            run_definition_id=definition["id"],
        )
        service = BillingRunService(table="billing_run", rsg=self.rsg)
        first_values = {
            "tenant_id": tenant_id,
            "account_id": account["id"],
            "subscription_id": subscription.id,
            "definition_id": definition["id"],
            "period_start": january,
            "period_end": february,
            "idempotency_key": "run-2026-01",
        }
        first = await service.create(first_values)
        duplicate = await service.create(first_values)
        self.assertEqual(duplicate.id, first.id)
        self.assertEqual(
            await service.action_start(
                tenant_id=tenant_id,
                entity_id=first.id,
                where={"tenant_id": tenant_id, "id": first.id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=1),
            ),
            ("", 204),
        )
        january_buckets = [
            row
            for row in self.rsg.rows["billing_entitlement_bucket"]
            if row["period_start"] == january
        ]
        self.assertEqual(len(january_buckets), 2)
        self.assertTrue(
            all(row["billing_run_id"] == first.id for row in january_buckets)
        )

        self.assertEqual(
            await service.action_complete(
                tenant_id=tenant_id,
                entity_id=first.id,
                where={"tenant_id": tenant_id, "id": first.id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=2),
            ),
            ("", 204),
        )
        self.assertEqual(
            await service.action_reconcile_entitlements(
                tenant_id=tenant_id,
                entity_id=first.id,
                where={"tenant_id": tenant_id, "id": first.id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=3),
            ),
            ("", 204),
        )
        self.assertEqual(len(self.rsg.rows["billing_entitlement_bucket"]), 4)

        second = await service.create(
            {
                **first_values,
                "period_start": february,
                "period_end": march,
                "idempotency_key": "run-2026-02",
            }
        )
        where = {"tenant_id": tenant_id, "id": second.id}
        await service.action_start(
            tenant_id=tenant_id,
            entity_id=second.id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=1),
        )
        await service.action_fail(
            tenant_id=tenant_id,
            entity_id=second.id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=BillingRunFailValidation(
                row_version=2,
                failure_code="processor_timeout",
                failure_detail="Processor did not respond",
            ),
        )
        retry_result = await service.action_retry(
            tenant_id=tenant_id,
            entity_id=second.id,
            where=where,
            auth_user_id=uuid.uuid4(),
            data=BillingRunRetryValidation(
                row_version=3,
                idempotency_key="run-2026-02-retry-1",
            ),
        )
        self.assertEqual(retry_result[1], 201)
        retry = self.rsg.rows["billing_run"][-1]
        self.assertEqual(retry["retry_of_run_id"], second.id)
        self.assertEqual(retry["attempt_number"], 2)

    async def test_invoice_inherits_global_defaults_and_tenant_scope(self) -> None:
        tenant_id = uuid.uuid4()
        reference_ids = {
            "tax_code_id": uuid.uuid4(),
            "payment_term_id": uuid.uuid4(),
            "invoice_template_id": uuid.uuid4(),
            "discount_definition_id": uuid.uuid4(),
        }
        for field_name, table_name in (
            ("tax_code_id", "billing_tax_code"),
            ("payment_term_id", "billing_payment_term"),
            ("invoice_template_id", "billing_invoice_template"),
            ("discount_definition_id", "billing_discount_definition"),
        ):
            await self.rsg.insert_one(
                table_name,
                {"id": reference_ids[field_name], "is_active": True},
            )
        account = await self.rsg.insert_one(
            "billing_account",
            {
                "tenant_id": tenant_id,
                "currency_definition_id": self.currency_id,
                "deleted_at": None,
                **reference_ids,
            },
        )
        subscription = await self._create_subscription(
            tenant_id,
            account["id"],
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        invoice = await InvoiceService(
            table="billing_invoice",
            rsg=self.rsg,
        ).create(
            {
                "tenant_id": tenant_id,
                "account_id": account["id"],
                "subscription_id": subscription.id,
                "invoice_number": "INV-1",
            }
        )
        self.assertEqual(invoice.currency_definition_id, self.currency_id)
        self.assertEqual(invoice.currency, "GYD")
        for field_name, expected in reference_ids.items():
            self.assertEqual(getattr(invoice, field_name), expected)

    async def test_catalog_lifecycle_immutability_and_tax_periods(self) -> None:
        meter_service = MeterDefinitionService(
            table="billing_meter_definition",
            rsg=self.rsg,
        )
        meter = await meter_service.create(
            {
                "code": " Demo.Meter ",
                "unit": " Unit ",
                "aggregation_mode": " SUM ",
                "description": " Demo ",
            }
        )
        self.assertEqual((meter.code, meter.unit), ("demo.meter", "unit"))
        updated = await meter_service.update_with_row_version(
            {"id": meter.id},
            expected_row_version=1,
            changes={"description": " Renamed "},
        )
        self.assertEqual(updated.description, "Renamed")
        self.assertEqual(
            await meter_service.entity_action_deactivate(
                entity_id=meter.id,
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=2),
            ),
            ("", 204),
        )
        self.assertEqual(
            await meter_service.entity_action_activate(
                entity_id=meter.id,
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=3),
            ),
            ("", 204),
        )
        await self.rsg.insert_one(
            "billing_usage_event",
            {"meter_definition_id": meter.id},
        )
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await meter_service.update(
                    {"id": meter.id},
                    {"aggregation_mode": "max"},
                )
        self.assertEqual(ex.exception.code, 409)

        tax_code = await TaxCodeService(
            table="billing_tax_code",
            rsg=self.rsg,
        ).create({"code": " VAT ", "display_name": " VAT "})
        tax_rate_service = TaxRateService(
            table="billing_tax_rate",
            rsg=self.rsg,
        )
        rate = await tax_rate_service.create(
            {
                "code": "GY-VAT-14",
                "tax_code_id": tax_code.id,
                "jurisdiction_code": " GY ",
                "rate_basis_points": 1400,
                "effective_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "effective_to": datetime(2027, 1, 1, tzinfo=timezone.utc),
            }
        )
        self.assertEqual(rate.jurisdiction_code, "gy")
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await tax_rate_service.create(
                    {
                        "code": "GY-VAT-15",
                        "tax_code_id": tax_code.id,
                        "jurisdiction_code": "gy",
                        "rate_basis_points": 1500,
                        "effective_from": datetime(2026, 6, 1, tzinfo=timezone.utc),
                        "effective_to": None,
                    }
                )
        self.assertEqual(ex.exception.code, 409)

        services = (
            CurrencyDefinitionService("billing_currency_definition", self.rsg),
            RunDefinitionService("billing_run_definition", self.rsg),
            PaymentTermService("billing_payment_term", self.rsg),
            InvoiceTemplateService("billing_invoice_template", self.rsg),
            DiscountDefinitionService("billing_discount_definition", self.rsg),
        )
        self.assertEqual(len(services), 5)

    async def test_price_entitlement_rules_freeze_after_subscription_use(self) -> None:
        service = PriceEntitlementService(
            table="billing_price_entitlement",
            rsg=self.rsg,
        )
        other_price = await self.rsg.insert_one(
            "billing_price",
            {
                "product_id": self.product_id,
                "price_type": "recurring",
                "interval_unit": "month",
                "interval_count": 1,
                "deleted_at": None,
            },
        )
        rule = await service.create(
            {
                "price_id": other_price["id"],
                "meter_definition_id": self.meter_ids[0],
                "included_quantity": 25,
                "rollover_policy": " NONE ",
            }
        )
        self.assertEqual(rule.rollover_policy, "none")
        updated = await service.update(
            {"id": rule.id},
            {"included_quantity": 30},
        )
        self.assertEqual(updated.included_quantity, 30)
        await self.rsg.insert_one(
            "billing_subscription",
            {"price_id": other_price["id"]},
        )
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.update(
                    {"id": rule.id},
                    {"included_quantity": 40},
                )
        self.assertEqual(ex.exception.code, 409)

        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                BillingRunService._validate_definition_period(
                    {
                        "frequency": "monthly",
                        "interval_count": 1,
                        "timezone": "UTC",
                    },
                    {
                        "period_start": datetime(2026, 1, 1, tzinfo=timezone.utc),
                        "period_end": datetime(2026, 1, 2, tzinfo=timezone.utc),
                    },
                )
        self.assertEqual(ex.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
