"""Failure-path coverage for normalized billing services."""

# pylint: disable=protected-access

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.billing.api.validation import (
    BillingEntitlementAdjustValidation,
    BillingRunFailValidation,
    BillingRunRetryValidation,
    BillingSubscriptionPeriodValidation,
)
from mugen.core.plugin.billing.domain import PriceDE
from mugen.core.plugin.billing.domain.catalog import PriceEntitlementDE, TaxRateDE
from mugen.core.plugin.billing.service import billing_run as billing_run_mod
from mugen.core.plugin.billing.service import catalog as catalog_mod
from mugen.core.plugin.billing.service import entitlement_bucket as bucket_mod
from mugen.core.plugin.billing.service import subscription as subscription_mod
from mugen.core.plugin.billing.service.account import AccountService
from mugen.core.plugin.billing.service.adjustment import AdjustmentService
from mugen.core.plugin.billing.service.billing_run import BillingRunService
from mugen.core.plugin.billing.service.catalog import (
    DiscountDefinitionService,
    MeterDefinitionService,
    PriceEntitlementService,
    TaxRateService,
)
from mugen.core.plugin.billing.service.credit_note import CreditNoteService
from mugen.core.plugin.billing.service.entitlement_adjustment import (
    EntitlementAdjustmentService,
)
from mugen.core.plugin.billing.service.entitlement_bucket import (
    EntitlementBucketService,
)
from mugen.core.plugin.billing.service.invoice import InvoiceService
from mugen.core.plugin.billing.service.invoice_line import InvoiceLineService
from mugen.core.plugin.billing.service.ledger_entry import LedgerEntryService
from mugen.core.plugin.billing.service.payment import PaymentService
from mugen.core.plugin.billing.service.price import PriceService
from mugen.core.plugin.billing.service.reference import BillingReferenceService
from mugen.core.plugin.billing.service.subscription import SubscriptionService
from mugen.core.plugin.billing.service.usage_allocation import UsageAllocationService
from mugen.core.plugin.billing.service.usage_event import UsageEventService
from mugen.core.plugin.ops_metering.service import meter_policy as meter_policy_mod
from mugen.core.plugin.ops_metering.service import usage_session as usage_session_mod
from mugen.core.plugin.ops_metering.service.meter_policy import MeterPolicyService
from mugen.core.plugin.ops_metering.service.usage_session import UsageSessionService
from mugen_test.test_billing_normalized_workflows import (
    _AbortCalled,
    _MemoryGateway,
    _abort_raiser,
)


class _AsyncCM:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class TestCatalogAndReferenceEdges(unittest.IsolatedAsyncioTestCase):
    """Exercise catalog conflict and generic-reference failure paths."""

    async def asyncSetUp(self) -> None:
        self.rsg = _MemoryGateway()
        self.meter_service = MeterDefinitionService(
            "billing_meter_definition",
            self.rsg,
        )

    async def test_global_definition_lookup_update_and_activation_edges(self) -> None:
        missing_id = uuid.uuid4()
        self.assertIsNone(
            await self.meter_service.update({"id": missing_id}, {"unit": "task"})
        )
        self.assertIsNone(
            await self.meter_service.update_with_row_version(
                {"id": missing_id},
                expected_row_version=1,
                changes={"unit": "task"},
            )
        )

        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            self.meter_service.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await self.meter_service._get_for_action(
                    entity_id=missing_id,
                    expected_row_version=1,
                )
            self.assertEqual(ex.exception.code, 500)

            self.meter_service.get = AsyncMock(
                side_effect=[None, SQLAlchemyError("db")]
            )
            with self.assertRaises(_AbortCalled) as ex:
                await self.meter_service._get_for_action(
                    entity_id=missing_id,
                    expected_row_version=1,
                )
            self.assertEqual(ex.exception.code, 500)

            self.meter_service.get = AsyncMock(side_effect=[None, None])
            with self.assertRaises(_AbortCalled) as ex:
                await self.meter_service._get_for_action(
                    entity_id=missing_id,
                    expected_row_version=1,
                )
            self.assertEqual(ex.exception.code, 404)

            self.meter_service.get = AsyncMock(
                side_effect=[None, SimpleNamespace(id=missing_id)]
            )
            with self.assertRaises(_AbortCalled) as ex:
                await self.meter_service._get_for_action(
                    entity_id=missing_id,
                    expected_row_version=1,
                )
            self.assertEqual(ex.exception.code, 409)

        self.meter_service = MeterDefinitionService(
            "billing_meter_definition",
            self.rsg,
        )
        meter = await self.meter_service.create(
            {"code": "edge", "unit": "unit", "aggregation_mode": "sum"}
        )
        self.assertEqual(
            await self.meter_service.entity_action_activate(
                entity_id=meter.id,
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=1),
            ),
            ("", 204),
        )
        await self.rsg.insert_one(
            "billing_price",
            {"meter_definition_id": meter.id},
        )
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.meter_service.entity_action_deactivate(
                    entity_id=meter.id,
                    auth_user_id=uuid.uuid4(),
                    data=RowVersionValidation(row_version=1),
                )
        self.assertEqual(ex.exception.code, 409)

        self.rsg.rows["billing_price"].clear()
        self.meter_service._get_for_action = AsyncMock(
            return_value=SimpleNamespace(is_active=True)
        )
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(side_effect=RowVersionConflict("meter")),
        ), patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.meter_service._set_active(
                    entity_id=meter.id,
                    expected_row_version=1,
                    active=False,
                )
        self.assertEqual(ex.exception.code, 409)
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(side_effect=SQLAlchemyError("db")),
        ), patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.meter_service._set_active(
                    entity_id=meter.id,
                    expected_row_version=1,
                    active=False,
                )
        self.assertEqual(ex.exception.code, 500)
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(return_value=None),
        ), patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.meter_service._set_active(
                    entity_id=meter.id,
                    expected_row_version=1,
                    active=False,
                )
        self.assertEqual(ex.exception.code, 404)

    async def test_price_entitlement_contract_and_archive_edges(self) -> None:
        service = PriceEntitlementService("billing_price_entitlement", self.rsg)
        price_id = uuid.uuid4()
        meter_id = uuid.uuid4()
        payload = {
            "price_id": price_id,
            "meter_definition_id": meter_id,
            "included_quantity": 1,
        }
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.create(payload)
            self.assertEqual(ex.exception.code, 409)

        price = await self.rsg.insert_one(
            "billing_price",
            {
                "id": price_id,
                "price_type": "one_time",
                "interval_unit": None,
                "interval_count": None,
                "deleted_at": None,
            },
        )
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await service.create(payload)
        stored_price = self.rsg.rows["billing_price"][0]
        stored_price.update(price_type="recurring")
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await service.create(payload)
        stored_price.update(interval_unit="month", interval_count=1)
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await service.create(payload)
        meter = await self.rsg.insert_one(
            "billing_meter_definition",
            {"id": meter_id, "is_active": False},
        )
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await service.create(payload)
        self.rsg.rows["billing_meter_definition"][0]["is_active"] = True
        await self.rsg.insert_one("billing_subscription", {"price_id": price_id})
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await service.create(payload)
            with self.assertRaises(_AbortCalled):
                await service._validate_update(
                    PriceEntitlementDE(price_id=None),
                    {"included_quantity": 2},
                )

        self.rsg.rows["billing_subscription"].clear()
        rule = await service.create(payload)
        archive_data = SimpleNamespace(row_version=rule.row_version)
        self.assertEqual(
            await service.entity_action_archive(
                entity_id=rule.id,
                auth_user_id=uuid.uuid4(),
                data=archive_data,
            ),
            ("", 204),
        )
        archived = await service.get({"id": rule.id})
        self.assertEqual(
            await service.entity_action_archive(
                entity_id=rule.id,
                auth_user_id=uuid.uuid4(),
                data=SimpleNamespace(row_version=archived.row_version),
            ),
            ("", 204),
        )

        current = PriceEntitlementDE(
            id=uuid.uuid4(),
            price_id=price_id,
            row_version=1,
        )
        service._get_for_action = AsyncMock(return_value=current)
        await self.rsg.insert_one("billing_subscription", {"price_id": price_id})
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.entity_action_archive(
                    entity_id=current.id,
                    auth_user_id=uuid.uuid4(),
                    data=SimpleNamespace(row_version=1),
                )
        self.assertEqual(ex.exception.code, 409)

        self.rsg.rows["billing_subscription"].clear()
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(side_effect=RowVersionConflict("rule")),
        ), patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.entity_action_archive(
                    entity_id=current.id,
                    auth_user_id=uuid.uuid4(),
                    data=SimpleNamespace(row_version=1),
                )
        self.assertEqual(ex.exception.code, 409)
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(return_value=None),
        ), patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.entity_action_archive(
                    entity_id=current.id,
                    auth_user_id=uuid.uuid4(),
                    data=SimpleNamespace(row_version=1),
                )
        self.assertEqual(ex.exception.code, 404)

    async def test_tax_rate_and_discount_reference_edges(self) -> None:
        tax_service = TaxRateService("billing_tax_rate", self.rsg)
        tax_code_id = uuid.uuid4()
        payload = {
            "code": "rate",
            "tax_code_id": tax_code_id,
            "jurisdiction_code": "gy",
            "rate_basis_points": 1,
            "effective_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "effective_to": datetime(2026, 2, 1, tzinfo=timezone.utc),
        }
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await tax_service.create(payload)
        await self.rsg.insert_one(
            "billing_tax_code",
            {"id": tax_code_id, "is_active": True},
        )
        await self.rsg.insert_one(
            "billing_tax_rate",
            {
                "id": uuid.uuid4(),
                "tax_code_id": tax_code_id,
                "jurisdiction_code": "gy",
                "effective_from": None,
                "effective_to": None,
                "is_active": True,
            },
        )
        rate = await tax_service.create(payload)
        updated = await tax_service.update(
            {"id": rate.id},
            {"effective_to": datetime(2026, 3, 1, tzinfo=timezone.utc)},
        )
        self.assertEqual(updated.effective_to.month, 3)

        candidate = TaxRateDE(
            id=rate.id,
            tax_code_id=tax_code_id,
            jurisdiction_code="gy",
            effective_from=payload["effective_from"],
            effective_to=payload["effective_to"],
            is_active=True,
        )
        tax_service.list = AsyncMock(return_value=[candidate])
        await tax_service._validate_tax_rate(
            payload,
            exclude_id=rate.id,
        )
        tax_service.list = AsyncMock(
            return_value=[
                TaxRateDE(
                    id=uuid.uuid4(),
                    effective_from=datetime(2027, 1, 1, tzinfo=timezone.utc),
                    effective_to=None,
                )
            ]
        )
        await tax_service._validate_tax_rate(payload)

        discount_service = DiscountDefinitionService(
            "billing_discount_definition",
            self.rsg,
        )
        currency_id = uuid.uuid4()
        with patch.object(catalog_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await discount_service.create(
                    {
                        "code": "fixed",
                        "currency_definition_id": currency_id,
                    }
                )
        await self.rsg.insert_one(
            "billing_currency_definition",
            {"id": currency_id, "is_active": True},
        )
        discount = await discount_service.create(
            {
                "code": "fixed",
                "currency_definition_id": currency_id,
            }
        )
        self.assertEqual(discount.currency_definition_id, currency_id)
        no_currency = await discount_service.create({"code": "percentage"})
        self.assertEqual(no_currency.code, "percentage")

    async def test_generic_reference_services_and_meter_consumers(self) -> None:
        services = (
            AccountService("billing_account", self.rsg),
            AdjustmentService("billing_adjustment", self.rsg),
            CreditNoteService("billing_credit_note", self.rsg),
            EntitlementAdjustmentService("billing_entitlement_adjustment", self.rsg),
            InvoiceLineService("billing_invoice_line", self.rsg),
            LedgerEntryService("billing_ledger_entry", self.rsg),
            PaymentService("billing_payment", self.rsg),
            UsageAllocationService("billing_usage_allocation", self.rsg),
        )
        self.assertEqual(len(services), 8)

        generic = BillingReferenceService(
            de_type=SimpleNamespace,
            table="generic",
            rsg=self.rsg,
        )
        generic._active_reference_tables = {
            "definition_id": ("definition", "DefinitionId")
        }
        with patch(
            "mugen.core.plugin.billing.service.reference.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await generic.create({"definition_id": uuid.uuid4()})
        self.assertEqual(ex.exception.code, 400)
        definition = await self.rsg.insert_one(
            "definition",
            {"is_active": True},
        )
        created = await generic.create({"definition_id": definition["id"]})
        self.assertEqual(created.definition_id, definition["id"])
        updated = await generic.update(
            {"id": created.id},
            {"definition_id": None},
        )
        self.assertIsNone(updated.definition_id)
        versioned = await generic.update_with_row_version(
            {"id": created.id},
            expected_row_version=updated.row_version,
            changes={"definition_id": definition["id"]},
        )
        self.assertEqual(versioned.definition_id, definition["id"])

        for module, service in (
            (
                meter_policy_mod,
                MeterPolicyService("ops_metering_meter_policy", self.rsg),
            ),
            (
                usage_session_mod,
                UsageSessionService("ops_metering_usage_session", self.rsg),
            ),
        ):
            with patch.object(module, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled):
                    await service.create({"meter_definition_id": uuid.uuid4()})

        usage_service = UsageEventService("billing_usage_event", self.rsg)
        with patch(
            "mugen.core.plugin.billing.service.usage_event.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled):
                await usage_service.create({"meter_definition_id": uuid.uuid4()})
        meter = await self.rsg.insert_one(
            "billing_meter_definition",
            {"code": "global", "is_active": True},
        )
        policy = await MeterPolicyService(
            "ops_metering_meter_policy",
            self.rsg,
        ).create({"meter_definition_id": meter["id"], "code": "global-policy"})
        session = await UsageSessionService(
            "ops_metering_usage_session",
            self.rsg,
        ).create({"meter_definition_id": meter["id"]})
        self.assertEqual(policy.meter_definition_id, meter["id"])
        self.assertEqual(session.meter_definition_id, meter["id"])
        event = await usage_service.create(
            {"meter_definition_id": meter["id"], "quantity": 1}
        )
        self.assertEqual(event.meter_code, "global")


class TestEntitlementBucketEdges(unittest.IsolatedAsyncioTestCase):
    """Cover adjustment conflict and storage failure translations."""

    async def asyncSetUp(self) -> None:
        self.rsg = _MemoryGateway()
        self.service = EntitlementBucketService(
            "billing_entitlement_bucket",
            self.rsg,
        )
        self.tenant_id = uuid.uuid4()
        self.bucket = await self.rsg.insert_one(
            "billing_entitlement_bucket",
            {
                "tenant_id": self.tenant_id,
                "account_id": uuid.uuid4(),
                "included_quantity": 10,
                "rollover_quantity": 0,
                "adjustment_quantity": 0,
                "consumed_quantity": 0,
            },
        )

    def _data(self, **changes):
        values = {
            "row_version": self.bucket["row_version"],
            "quantity_delta": 1,
            "reason": "reason",
            "idempotency_key": "key",
        }
        values.update(changes)
        return BillingEntitlementAdjustValidation(**values)

    async def _call(self, data=None):
        return await self.service.action_adjust(
            tenant_id=self.tenant_id,
            entity_id=self.bucket["id"],
            where={"tenant_id": self.tenant_id, "id": self.bucket["id"]},
            auth_user_id=uuid.uuid4(),
            data=data or self._data(),
        )

    async def test_adjustment_conflicts_and_missing_bucket(self) -> None:
        await self.rsg.insert_one(
            "billing_entitlement_adjustment",
            {
                "tenant_id": self.tenant_id,
                "idempotency_key": "key",
                "bucket_id": uuid.uuid4(),
                "quantity_delta": 2,
                "reason": "other",
            },
        )
        with patch.object(bucket_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self._call()
        self.assertEqual(ex.exception.code, 409)
        self.rsg.rows["billing_entitlement_adjustment"].clear()

        with patch.object(bucket_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self._call(self._data(row_version=99))
        self.assertEqual(ex.exception.code, 409)
        self.rsg.rows["billing_entitlement_bucket"].clear()
        with patch.object(bucket_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self._call()
        self.assertEqual(ex.exception.code, 404)

    async def test_adjustment_write_error_translations(self) -> None:
        uow = Mock()
        uow.get_one = AsyncMock(side_effect=[None, dict(self.bucket)])
        uow.update_one = AsyncMock(return_value=None)
        self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
        with patch.object(bucket_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self._call()
        self.assertEqual(ex.exception.code, 409)

        for error, expected in (
            (RowVersionConflict("bucket"), 409),
            (IntegrityError("stmt", {}, Exception("db")), 409),
            (SQLAlchemyError("db"), 500),
        ):
            uow = Mock()
            uow.get_one = AsyncMock(side_effect=error)
            self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
            with patch.object(bucket_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self._call()
            self.assertEqual(ex.exception.code, expected)


class TestSubscriptionServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Cover catalog validation, legacy adoption, and action conflict paths."""

    async def asyncSetUp(self) -> None:
        self.rsg = _MemoryGateway()
        self.service = SubscriptionService("billing_subscription", self.rsg)
        self.tenant_id = uuid.uuid4()
        self.account_id = uuid.uuid4()
        self.product_id = uuid.uuid4()
        self.price_id = uuid.uuid4()
        self.meter_id = uuid.uuid4()
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.end = datetime(2026, 2, 1, tzinfo=timezone.utc)

    async def _seed_contract(self) -> None:
        await self.rsg.insert_one(
            "billing_account",
            {
                "id": self.account_id,
                "tenant_id": self.tenant_id,
                "deleted_at": None,
            },
        )
        await self.rsg.insert_one(
            "billing_product",
            {"id": self.product_id, "deleted_at": None},
        )
        await self.rsg.insert_one(
            "billing_price",
            {
                "id": self.price_id,
                "product_id": self.product_id,
                "price_type": "recurring",
                "interval_unit": "month",
                "interval_count": 1,
                "deleted_at": None,
            },
        )
        await self.rsg.insert_one(
            "billing_meter_definition",
            {
                "id": self.meter_id,
                "code": "meter",
                "is_active": True,
            },
        )
        await self.rsg.insert_one(
            "billing_price_entitlement",
            {
                "price_id": self.price_id,
                "meter_definition_id": self.meter_id,
                "included_quantity": 10,
                "rollover_policy": "none",
                "deleted_at": None,
            },
        )

    def _subscription_record(self, **changes):
        record = {
            "id": uuid.uuid4(),
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "price_id": self.price_id,
            "status": "active",
            "current_period_start": self.start,
            "current_period_end": self.end,
            "row_version": 1,
        }
        record.update(changes)
        return record

    async def test_interval_and_catalog_contract_edges(self) -> None:
        naive = datetime(2026, 1, 1)
        self.assertIsNotNone(self.service._as_utc(naive).tzinfo)
        aware = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-4)))
        self.assertEqual(
            self.service._as_utc(aware).hour,
            4,
        )
        for unit, expected in (("day", 2), ("week", 8), ("year", 1)):
            result = self.service._add_interval(
                self.start,
                unit,
                1,
            )
            self.assertEqual(result.day, expected)
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                self.service._add_interval(self.start, "hour", 1)

        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._load_catalog_contract(
                    self.rsg,
                    tenant_id=self.tenant_id,
                    account_id=self.account_id,
                    price_id=self.price_id,
                    references={},
                    status_code=400,
                )
        await self.rsg.insert_one(
            "billing_account",
            {
                "id": self.account_id,
                "tenant_id": self.tenant_id,
                "deleted_at": None,
            },
        )
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._load_catalog_contract(
                    self.rsg,
                    tenant_id=self.tenant_id,
                    account_id=self.account_id,
                    price_id=self.price_id,
                    references={},
                    status_code=400,
                )
        price = await self.rsg.insert_one(
            "billing_price",
            {
                "id": self.price_id,
                "product_id": self.product_id,
                "price_type": "one_time",
                "deleted_at": None,
            },
        )
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._load_catalog_contract(
                    self.rsg,
                    tenant_id=self.tenant_id,
                    account_id=self.account_id,
                    price_id=self.price_id,
                    references={},
                    status_code=400,
                )
        await self.rsg.insert_one(
            "billing_product",
            {"id": self.product_id, "deleted_at": None},
        )
        stored_price = self.rsg.rows["billing_price"][0]
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._load_catalog_contract(
                    self.rsg,
                    tenant_id=self.tenant_id,
                    account_id=self.account_id,
                    price_id=self.price_id,
                    references={},
                    status_code=400,
                )
        stored_price.update(price_type="recurring")
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._load_catalog_contract(
                    self.rsg,
                    tenant_id=self.tenant_id,
                    account_id=self.account_id,
                    price_id=self.price_id,
                    references={},
                    status_code=400,
                )
        stored_price.update(interval_unit="month", interval_count=1)
        definition_id = uuid.uuid4()
        await self.rsg.insert_one(
            "billing_run_definition",
            {"id": definition_id, "is_active": False},
        )
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._load_catalog_contract(
                    self.rsg,
                    tenant_id=self.tenant_id,
                    account_id=self.account_id,
                    price_id=self.price_id,
                    references={"run_definition_id": definition_id},
                    status_code=400,
                )
        self.rsg.rows["billing_run_definition"][0]["is_active"] = True
        resolved_price, resolved_account = await self.service._load_catalog_contract(
            self.rsg,
            tenant_id=self.tenant_id,
            account_id=self.account_id,
            price_id=self.price_id,
            references={"run_definition_id": definition_id},
            status_code=400,
        )
        self.assertEqual(
            (resolved_price["id"], resolved_account["id"]),
            (self.price_id, self.account_id),
        )

        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                self.service._period_for_create(
                    {
                        "current_period_start": self.end,
                        "current_period_end": self.start,
                    },
                    stored_price,
                )
        payload = {
            "current_period_start": self.start,
            "current_period_end": self.end,
        }
        self.assertEqual(
            self.service._period_for_create(payload, stored_price),
            (self.start, self.end),
        )

    async def test_bucket_conflicts_and_legacy_adoption(self) -> None:
        await self._seed_contract()
        subscription = self._subscription_record()
        rule = self.rsg.rows["billing_price_entitlement"][0]
        meter = self.rsg.rows["billing_meter_definition"][0]
        identity = {
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "subscription_id": subscription["id"],
            "price_entitlement_id": rule["id"],
            "period_start": self.start,
            "period_end": self.end,
        }
        await self.rsg.insert_one(
            "billing_entitlement_bucket",
            {
                **identity,
                "price_id": self.price_id,
                "meter_definition_id": self.meter_id,
                "included_quantity": 99,
            },
        )
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._provision_buckets(
                    self.rsg,
                    subscription=subscription,
                    period_start=self.start,
                    period_end=self.end,
                    generation_source="test",
                )
        self.rsg.rows["billing_entitlement_bucket"].clear()
        meter["is_active"] = False
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._provision_buckets(
                    self.rsg,
                    subscription=subscription,
                    period_start=self.start,
                    period_end=self.end,
                    generation_source="test",
                )
        meter["is_active"] = True

        legacy = {
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "subscription_id": subscription["id"],
            "price_id": self.price_id,
            "meter_code": "meter",
            "period_start": self.start,
            "period_end": self.end,
            "price_entitlement_id": None,
            "included_quantity": 10,
        }
        first = await self.rsg.insert_one("billing_entitlement_bucket", legacy)
        generated = await self.service._provision_buckets(
            self.rsg,
            subscription=subscription,
            period_start=self.start,
            period_end=self.end,
            generation_source="reconciliation",
        )
        self.assertEqual(generated, 1)
        self.assertEqual(
            self.rsg.rows["billing_entitlement_bucket"][0]["price_entitlement_id"],
            rule["id"],
        )

        for count, quantity in ((2, 10), (1, 9)):
            self.rsg.rows["billing_entitlement_bucket"].clear()
            for _ in range(count):
                await self.rsg.insert_one(
                    "billing_entitlement_bucket",
                    {**legacy, "included_quantity": quantity},
                )
            with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled):
                    await self.service._provision_buckets(
                        self.rsg,
                        subscription=subscription,
                        period_start=self.start,
                        period_end=self.end,
                        generation_source="test",
                    )
        self.assertIsNotNone(first["id"])

    async def test_create_update_and_reactivation_edges(self) -> None:
        await self._seed_contract()
        account = self.rsg.rows["billing_account"][0]
        definition_id = uuid.uuid4()
        await self.rsg.insert_one(
            "billing_run_definition",
            {"id": definition_id, "is_active": True},
        )
        validated = await self.service._validate_reference_changes(
            {"run_definition_id": definition_id}
        )
        self.assertEqual(validated["run_definition_id"], definition_id)
        created_for_update = await self.rsg.insert_one(
            "billing_subscription",
            self._subscription_record(),
        )
        updated = await self.service.update(
            {"id": created_for_update["id"]},
            {"run_definition_id": definition_id},
        )
        versioned = await self.service.update_with_row_version(
            {"id": created_for_update["id"]},
            expected_row_version=updated.row_version,
            changes={"run_definition_id": None},
        )
        self.assertIsNone(versioned.run_definition_id)
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._validate_reference_changes(
                    {"run_definition_id": uuid.uuid4()}
                )

        subscription = await self.rsg.insert_one(
            "billing_subscription",
            self._subscription_record(status="canceled"),
        )
        where = {"tenant_id": self.tenant_id, "id": subscription["id"]}
        result = await self.service.action_reactivate(
            tenant_id=self.tenant_id,
            entity_id=subscription["id"],
            where=where,
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=1),
        )
        self.assertEqual(result, ("", 204))
        self.assertEqual(self.rsg.rows["billing_subscription"][0]["status"], "active")

        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.action_reactivate(
                    tenant_id=self.tenant_id,
                    entity_id=subscription["id"],
                    where=where,
                    auth_user_id=uuid.uuid4(),
                    data=RowVersionValidation(row_version=2),
                )
        self.assertEqual(ex.exception.code, 409)

        uow = Mock()
        uow.insert = AsyncMock(return_value=None)
        self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
        self.service._load_catalog_contract = AsyncMock(
            return_value=(
                {"interval_unit": "month", "interval_count": 1},
                account,
            )
        )
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.create(
                    {
                        "tenant_id": self.tenant_id,
                        "account_id": self.account_id,
                        "price_id": self.price_id,
                        "started_at": self.start,
                    }
                )
        self.assertEqual(ex.exception.code, 500)

        for error, expected in (
            (IntegrityError("stmt", {}, Exception("db")), 409),
            (SQLAlchemyError("db"), 500),
        ):
            uow = Mock()
            uow.insert = AsyncMock(side_effect=error)
            self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
            with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self.service.create(
                        {
                            "tenant_id": self.tenant_id,
                            "account_id": self.account_id,
                            "price_id": self.price_id,
                            "started_at": self.start,
                        }
                    )
            self.assertEqual(ex.exception.code, expected)

    async def test_action_storage_error_translations(self) -> None:
        current = self._subscription_record(status="canceled")
        common = {
            "tenant_id": self.tenant_id,
            "entity_id": current["id"],
            "where": {"tenant_id": self.tenant_id, "id": current["id"]},
            "auth_user_id": uuid.uuid4(),
        }
        for error, expected in (
            (RowVersionConflict("subscription"), 409),
            (IntegrityError("stmt", {}, Exception("db")), 409),
            (SQLAlchemyError("db"), 500),
        ):
            uow = Mock()
            uow.get_one = AsyncMock(return_value=current)
            self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
            self.service._load_catalog_contract = AsyncMock(side_effect=error)
            with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self.service.action_reactivate(
                        **common,
                        data=RowVersionValidation(row_version=1),
                    )
            self.assertEqual(ex.exception.code, expected)

        uow = Mock()
        uow.get_one = AsyncMock(return_value=current)
        uow.update_one = AsyncMock(return_value=None)
        self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
        self.service._load_catalog_contract = AsyncMock()
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.action_reactivate(
                    **common,
                    data=RowVersionValidation(row_version=1),
                )
        self.assertEqual(ex.exception.code, 409)

        for action_name in ("action_reactivate", "action_advance_period"):
            uow.get_one = AsyncMock(side_effect=[None, current])
            action = getattr(self.service, action_name)
            data = (
                RowVersionValidation(row_version=1)
                if action_name == "action_reactivate"
                else BillingSubscriptionPeriodValidation(row_version=1)
            )
            with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action(**common, data=data)
            self.assertEqual(ex.exception.code, 409)

            uow.get_one = AsyncMock(side_effect=[None, None])
            with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await action(**common, data=data)
            self.assertEqual(ex.exception.code, 404)

        active = self._subscription_record(status="active")
        price = {"interval_unit": "month", "interval_count": 1}
        uow.get_one = AsyncMock(side_effect=[active, price])
        uow.update_one = AsyncMock(return_value=None)
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_advance_period(
                    **common,
                    data=BillingSubscriptionPeriodValidation(row_version=1),
                )
        for error, expected in (
            (RowVersionConflict("subscription"), 409),
            (SQLAlchemyError("db"), 500),
        ):
            uow.get_one = AsyncMock(side_effect=error)
            with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self.service.action_advance_period(
                        **common,
                        data=BillingSubscriptionPeriodValidation(row_version=1),
                    )
            self.assertEqual(ex.exception.code, expected)

        for error, expected in (
            (RowVersionConflict("subscription"), 409),
            (SQLAlchemyError("db"), 500),
        ):
            uow.get_one = AsyncMock(side_effect=error)
            with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self.service.action_reconcile_entitlements(
                        **common,
                        data=BillingSubscriptionPeriodValidation(row_version=1),
                    )
            self.assertEqual(ex.exception.code, expected)

        uow.get_one = AsyncMock(side_effect=[None, active])
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.action_reconcile_entitlements(
                    **common,
                    data=BillingSubscriptionPeriodValidation(row_version=1),
                )
        self.assertEqual(ex.exception.code, 409)

    async def test_advance_and_reconcile_rejections(self) -> None:
        await self._seed_contract()
        subscription = await self.rsg.insert_one(
            "billing_subscription",
            self._subscription_record(status="paused"),
        )
        where = {"tenant_id": self.tenant_id, "id": subscription["id"]}
        common = {
            "tenant_id": self.tenant_id,
            "entity_id": subscription["id"],
            "where": where,
            "auth_user_id": uuid.uuid4(),
        }
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_advance_period(
                    **common,
                    data=BillingSubscriptionPeriodValidation(row_version=1),
                )
        stored = self.rsg.rows["billing_subscription"][0]
        stored.update(status="active")
        self.rsg.rows["billing_price"].clear()
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_advance_period(
                    **common,
                    data=BillingSubscriptionPeriodValidation(row_version=1),
                )
        await self.rsg.insert_one(
            "billing_price",
            {
                "id": self.price_id,
                "interval_unit": "month",
                "interval_count": 1,
                "deleted_at": None,
            },
        )
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_advance_period(
                    **common,
                    data=BillingSubscriptionPeriodValidation(
                        row_version=1,
                        period_start=self.start,
                        period_end=self.end,
                    ),
                )
            with self.assertRaises(_AbortCalled):
                await self.service.action_reconcile_entitlements(
                    **common,
                    data=BillingSubscriptionPeriodValidation(
                        row_version=1,
                        period_start=self.start,
                        period_end=self.end,
                    ),
                )
        stored.update(status="canceled")
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_reconcile_entitlements(
                    **common,
                    data=BillingSubscriptionPeriodValidation(row_version=1),
                )

        self.rsg.rows["billing_subscription"].clear()
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.action_reconcile_entitlements(
                    **common,
                    data=BillingSubscriptionPeriodValidation(row_version=1),
                )
        self.assertEqual(ex.exception.code, 404)


class TestBillingRunServiceEdges(unittest.IsolatedAsyncioTestCase):
    """Cover execution scope, idempotency, transition, and retry conflicts."""

    async def asyncSetUp(self) -> None:
        self.rsg = _MemoryGateway()
        self.service = BillingRunService("billing_run", self.rsg)
        self.tenant_id = uuid.uuid4()
        self.account_id = uuid.uuid4()
        self.subscription_id = uuid.uuid4()
        self.definition_id = uuid.uuid4()
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        await self.rsg.insert_one(
            "billing_run_definition",
            {
                "id": self.definition_id,
                "frequency": "monthly",
                "interval_count": 1,
                "timezone": "UTC",
                "is_active": True,
            },
        )
        await self.rsg.insert_one(
            "billing_account",
            {
                "id": self.account_id,
                "tenant_id": self.tenant_id,
                "deleted_at": None,
            },
        )
        await self.rsg.insert_one(
            "billing_subscription",
            {
                "id": self.subscription_id,
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "status": "active",
                "row_version": 1,
                "current_period_start": self.start,
                "current_period_end": self.end,
            },
        )

    def _values(self, **changes):
        values = {
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "subscription_id": self.subscription_id,
            "definition_id": self.definition_id,
            "period_start": self.start,
            "period_end": self.end,
            "idempotency_key": "run-1",
        }
        values.update(changes)
        return values

    def _run(self, **changes):
        values = {
            "id": uuid.uuid4(),
            **self._values(),
            "status": "pending",
            "attempt_number": 1,
            "row_version": 1,
        }
        values.update(changes)
        return values

    async def test_scope_and_period_helpers(self) -> None:
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service._validate_scope(
                    self.rsg,
                    self._values(definition_id=uuid.uuid4()),
                    status_code=400,
                )
            with self.assertRaises(_AbortCalled):
                await self.service._validate_scope(
                    self.rsg,
                    self._values(account_id=uuid.uuid4()),
                    status_code=400,
                )
            with self.assertRaises(_AbortCalled):
                await self.service._validate_scope(
                    self.rsg,
                    self._values(subscription_id=uuid.uuid4()),
                    status_code=400,
                )

        definition = self.rsg.rows["billing_run_definition"][0]
        definition["frequency"] = "manual"
        resolved = await self.service._validate_scope(
            self.rsg,
            self._values(account_id=None, subscription_id=None),
            status_code=400,
        )
        self.assertEqual(resolved["id"], self.definition_id)
        self.service._validate_definition_period(
            definition,
            self._values(),
        )
        for frequency, expected_day in (
            ("daily", 2),
            ("weekly", 8),
            ("yearly", 1),
        ):
            value = self.service._add_local_interval(
                self.start,
                frequency,
                1,
            )
            self.assertEqual(value.day, expected_day)

    async def test_create_idempotency_and_storage_errors(self) -> None:
        existing = await self.rsg.insert_one("billing_run", self._run())
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.create(
                    self._values(period_end=self.end + timedelta(days=1))
                )
        self.assertEqual(ex.exception.code, 409)
        self.rsg.rows["billing_run"].clear()

        uow = Mock()
        uow.insert = AsyncMock(return_value=None)
        self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
        self.service._validate_scope = AsyncMock()
        self.service.get = AsyncMock(return_value=None)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.create(self._values())
        self.assertEqual(ex.exception.code, 500)

        for recovered, expected in ((SimpleNamespace(**existing), None), (None, 409)):
            uow.insert = AsyncMock(
                side_effect=IntegrityError("stmt", {}, Exception("db"))
            )
            self.service.get = AsyncMock(side_effect=[None, recovered])
            if recovered is not None:
                result = await self.service.create(self._values())
                self.assertEqual(result.id, existing["id"])
            else:
                with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as ex:
                        await self.service.create(self._values())
                self.assertEqual(ex.exception.code, expected)

        uow.insert = AsyncMock(side_effect=SQLAlchemyError("db"))
        self.service.get = AsyncMock(return_value=None)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.create(self._values())
        self.assertEqual(ex.exception.code, 500)

    async def test_action_lookup_provisioning_and_transitions(self) -> None:
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service._load_action_run(
                    self.rsg,
                    where={"id": uuid.uuid4()},
                    row_version=1,
                )
        self.assertEqual(ex.exception.code, 404)
        run = await self.rsg.insert_one("billing_run", self._run())
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service._load_action_run(
                    self.rsg,
                    where={"id": run["id"]},
                    row_version=99,
                )
        self.assertEqual(ex.exception.code, 409)

        subscription = self.rsg.rows["billing_subscription"][0]
        self.service._subscription_service._provision_buckets = AsyncMock(
            return_value=0
        )
        unscoped = {**run, "account_id": None, "subscription_id": None}
        self.assertEqual(
            await self.service._provision_scoped_subscriptions(
                self.rsg,
                unscoped,
                allow_advance=False,
            ),
            0,
        )
        subscription["current_period_start"] = self.start - timedelta(days=1)
        subscription["current_period_end"] = self.start - timedelta(hours=1)
        generated = await self.service._provision_scoped_subscriptions(
            self.rsg,
            run,
            allow_advance=True,
        )
        self.assertEqual(generated, 0)
        subscription["current_period_end"] = self.start
        self.rsg.update_one = AsyncMock(return_value=None)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service._provision_scoped_subscriptions(
                    self.rsg,
                    run,
                    allow_advance=True,
                )
        self.assertEqual(ex.exception.code, 409)

        uow = Mock()
        current = self._run(status="succeeded")
        self.service._load_action_run = AsyncMock(return_value=current)
        uow.update_one = AsyncMock(return_value=current)
        self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service._transition(
                    where={"id": current["id"]},
                    row_version=1,
                    allowed={"running"},
                    changes={"status": "failed"},
                )
        self.assertEqual(ex.exception.code, 409)

        current["status"] = "running"
        uow.update_one = AsyncMock(return_value=None)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service._transition(
                    where={"id": current["id"]},
                    row_version=1,
                    allowed={"running"},
                    changes={"status": "failed"},
                )
        self.assertEqual(ex.exception.code, 409)

        for error, expected in (
            (RowVersionConflict("run"), 409),
            (SQLAlchemyError("db"), 500),
        ):
            self.service._load_action_run = AsyncMock(side_effect=error)
            with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self.service._transition(
                        where={"id": current["id"]},
                        row_version=1,
                        allowed={"running"},
                        changes={"status": "failed"},
                    )
            self.assertEqual(ex.exception.code, expected)

    async def test_start_cancel_retry_and_reconcile_edges(self) -> None:
        run = self._run(status="running")
        common = {
            "tenant_id": self.tenant_id,
            "entity_id": run["id"],
            "where": {"tenant_id": self.tenant_id, "id": run["id"]},
            "auth_user_id": uuid.uuid4(),
        }
        uow = Mock()
        self.rsg.unit_of_work = Mock(return_value=_AsyncCM(uow))
        self.service._load_action_run = AsyncMock(return_value=run)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_start(
                    **common,
                    data=RowVersionValidation(row_version=1),
                )
        run["status"] = "pending"
        self.service._validate_scope = AsyncMock()
        uow.update_one = AsyncMock(return_value=None)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_start(
                    **common,
                    data=RowVersionValidation(row_version=1),
                )

        for error, expected in (
            (IntegrityError("stmt", {}, Exception("db")), 409),
            (SQLAlchemyError("db"), 500),
        ):
            self.service._load_action_run = AsyncMock(side_effect=error)
            with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self.service.action_start(
                        **common,
                        data=RowVersionValidation(row_version=1),
                    )
            self.assertEqual(ex.exception.code, expected)

        self.service._transition = AsyncMock(return_value=("", 204))
        self.assertEqual(
            await self.service.action_cancel(
                **common,
                data=RowVersionValidation(row_version=1),
            ),
            ("", 204),
        )

        failed = self._run(status="pending", completed_at=self.end)
        self.service._load_action_run = AsyncMock(return_value=failed)
        retry_data = BillingRunRetryValidation(
            row_version=1,
            idempotency_key="retry-1",
        )
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_retry(**common, data=retry_data)
        failed["status"] = "failed"
        existing_retry = self._run(retry_of_run_id=failed["id"])
        uow.get_one = AsyncMock(return_value=existing_retry)
        result = await self.service.action_retry(**common, data=retry_data)
        self.assertEqual(result, ({"Id": str(existing_retry["id"])}, 200))
        uow.get_one = AsyncMock(return_value=self._run(retry_of_run_id=uuid.uuid4()))
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_retry(**common, data=retry_data)

        uow.get_one = AsyncMock(return_value=None)
        uow.update_one = AsyncMock(return_value=None)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_retry(**common, data=retry_data)
        uow.update_one = AsyncMock(return_value=failed)
        uow.insert = AsyncMock(return_value=None)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.action_retry(**common, data=retry_data)
        self.assertEqual(ex.exception.code, 500)

        for error, expected in (
            (RowVersionConflict("run"), 409),
            (SQLAlchemyError("db"), 500),
        ):
            self.service._load_action_run = AsyncMock(side_effect=error)
            with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self.service.action_retry(**common, data=retry_data)
            self.assertEqual(ex.exception.code, expected)

        pending = self._run(status="pending")
        self.service._load_action_run = AsyncMock(return_value=pending)
        with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await self.service.action_reconcile_entitlements(
                    **common,
                    data=RowVersionValidation(row_version=1),
                )
        for error, expected in (
            (RowVersionConflict("run"), 409),
            (SQLAlchemyError("db"), 500),
        ):
            self.service._load_action_run = AsyncMock(side_effect=error)
            with patch.object(billing_run_mod, "abort", side_effect=_abort_raiser):
                with self.assertRaises(_AbortCalled) as ex:
                    await self.service.action_reconcile_entitlements(
                        **common,
                        data=RowVersionValidation(row_version=1),
                    )
            self.assertEqual(ex.exception.code, expected)


class TestInvoiceAndPriceReferenceEdges(unittest.IsolatedAsyncioTestCase):
    """Cover tenant invoice scope and Price-to-definition consistency."""

    async def asyncSetUp(self) -> None:
        self.rsg = _MemoryGateway()
        self.tenant_id = uuid.uuid4()
        self.account_id = uuid.uuid4()
        self.currency_id = uuid.uuid4()
        await self.rsg.insert_one(
            "billing_currency_definition",
            {"id": self.currency_id, "code": "USD", "is_active": True},
        )

    async def test_invoice_scope_and_currency_rejections(self) -> None:
        service = InvoiceService("billing_invoice", self.rsg)
        base = {"tenant_id": self.tenant_id, "account_id": self.account_id}
        with patch(
            "mugen.core.plugin.billing.service.invoice.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled):
                await service.create(base)
        account = await self.rsg.insert_one(
            "billing_account",
            {
                "id": self.account_id,
                "tenant_id": self.tenant_id,
                "deleted_at": None,
            },
        )
        with patch(
            "mugen.core.plugin.billing.service.invoice.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled):
                await service.create({**base, "subscription_id": uuid.uuid4()})
            with self.assertRaises(_AbortCalled):
                await service.create({**base, "billing_run_id": uuid.uuid4()})
        subscription = await self.rsg.insert_one(
            "billing_subscription",
            {
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "price_id": uuid.uuid4(),
            },
        )
        wrong_account = uuid.uuid4()
        run = await self.rsg.insert_one(
            "billing_run",
            {
                "tenant_id": self.tenant_id,
                "account_id": wrong_account,
                "subscription_id": subscription["id"],
            },
        )
        with patch(
            "mugen.core.plugin.billing.service.invoice.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled):
                await service.create({**base, "billing_run_id": run["id"]})
        self.rsg.rows["billing_run"][0]["account_id"] = self.account_id
        self.rsg.rows["billing_run"][0]["subscription_id"] = uuid.uuid4()
        with patch(
            "mugen.core.plugin.billing.service.invoice.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled):
                await service.create(
                    {
                        **base,
                        "subscription_id": subscription["id"],
                        "billing_run_id": run["id"],
                    }
                )
        self.rsg.rows["billing_run"][0]["subscription_id"] = subscription["id"]
        with patch(
            "mugen.core.plugin.billing.service.invoice.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled):
                await service.create({**base, "subscription_id": subscription["id"]})
            with self.assertRaises(_AbortCalled):
                await service.create(base)

        price_currency = uuid.uuid4()
        await self.rsg.insert_one(
            "billing_currency_definition",
            {"id": price_currency, "code": "GYD", "is_active": True},
        )
        await self.rsg.insert_one(
            "billing_price",
            {"id": subscription["price_id"], "currency_definition_id": price_currency},
        )
        with patch(
            "mugen.core.plugin.billing.service.invoice.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled):
                await service.create(
                    {
                        **base,
                        "subscription_id": subscription["id"],
                        "currency_definition_id": self.currency_id,
                    }
                )
        self.rsg.rows["billing_account"][0]["currency_definition_id"] = self.currency_id
        invoice = await service.create(base)
        self.assertEqual(invoice.currency, "USD")

        tax_code = await self.rsg.insert_one(
            "billing_tax_code",
            {"is_active": True},
        )
        self.rsg.rows["billing_account"][0]["tax_code_id"] = tax_code["id"]
        inherited = await service.create(
            {
                **base,
                "subscription_id": subscription["id"],
                "currency_definition_id": price_currency,
            }
        )
        self.assertEqual(inherited.tax_code_id, tax_code["id"])
        self.rsg.rows["billing_run"][0].update(
            account_id=self.account_id,
            subscription_id=None,
        )
        scoped = await service.create(
            {
                **base,
                "subscription_id": subscription["id"],
                "billing_run_id": run["id"],
                "currency_definition_id": price_currency,
                "tax_code_id": tax_code["id"],
            }
        )
        self.assertEqual(scoped.billing_run_id, run["id"])
        self.assertIsNotNone(account["id"])

    async def test_price_reference_rejections_and_snapshot_updates(self) -> None:
        service = PriceService("billing_price", self.rsg)
        values = {
            "currency_definition_id": self.currency_id,
            "price_type": "metered",
            "meter_definition_id": uuid.uuid4(),
        }
        with patch(
            "mugen.core.plugin.billing.service.price.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled):
                await service._apply_reference_contract(values)
            with self.assertRaises(_AbortCalled):
                await service._apply_reference_contract(
                    {
                        "currency_definition_id": self.currency_id,
                        "price_type": "metered",
                    }
                )
            with self.assertRaises(_AbortCalled):
                await service._apply_reference_contract(
                    {
                        "currency_definition_id": self.currency_id,
                        "price_type": "recurring",
                        "meter_definition_id": uuid.uuid4(),
                    }
                )
        meter = await self.rsg.insert_one(
            "billing_meter_definition",
            {"code": "minutes", "unit": "minute", "is_active": True},
        )
        values["meter_definition_id"] = meter["id"]
        await service._apply_reference_contract(values)
        self.assertEqual(
            (values["meter_code"], values["usage_unit"]), ("minutes", "minute")
        )
        current = PriceDE(
            id=None,
            product_id=uuid.uuid4(),
            price_type="recurring",
            currency_definition_id=self.currency_id,
            meter_definition_id=None,
        )
        changes = await service._validate_update(
            current,
            {"price_type": "metered", "meter_definition_id": meter["id"]},
        )
        self.assertEqual(
            (changes["currency"], changes["meter_code"], changes["usage_unit"]),
            ("USD", "minutes", "minute"),
        )


if __name__ == "__main__":
    unittest.main()
