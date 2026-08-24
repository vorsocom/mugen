"""Focused tests for the global Billing Product and Price catalog."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import os
import subprocess
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.billing.api.validation import (
    BillingPriceCreateValidation,
    BillingPriceUpdateValidation,
    BillingProductCreateValidation,
    BillingProductUpdateValidation,
)
from mugen.core.plugin.billing.contrib import contribute
from mugen.core.plugin.billing.domain import PriceDE, ProductDE
from mugen.core.plugin.billing.edm import price_type, product_type
from mugen.core.plugin.billing.model import Price, Product
from mugen.core.plugin.billing.service import price as price_mod
from mugen.core.plugin.billing.service import product as product_mod
from mugen.core.plugin.billing.service import subscription as subscription_mod
from mugen.core.plugin.billing.service.price import PriceService
from mugen.core.plugin.billing.service.product import ProductService
from mugen.core.plugin.billing.service.subscription import SubscriptionService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None, **_kwargs):
    raise _AbortCalled(code, message)


def _rsg(**overrides):
    values = {
        "insert_one": AsyncMock(return_value={"id": uuid.uuid4()}),
        "update_one": AsyncMock(return_value={"id": uuid.uuid4()}),
        "get_one": AsyncMock(return_value=None),
        "count_many": AsyncMock(return_value=0),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestBillingGlobalCatalogContract(unittest.TestCase):
    """Covers EDM, validation, model, and ACP permission contracts."""

    def test_product_and_price_edm_are_global_and_price_has_no_tenant_reverse_navs(
        self,
    ) -> None:
        self.assertNotIn("TenantId", product_type.properties)
        self.assertNotIn("Tenant", product_type.nav_properties)
        self.assertNotIn("TenantId", price_type.properties)
        self.assertNotIn("Tenant", price_type.nav_properties)
        self.assertEqual(
            set(price_type.nav_properties),
            {"DeletedByUser", "Product"},
        )
        self.assertTrue(price_type.properties["MeterCode"].nullable)

    def test_models_use_global_keys_and_global_foreign_keys(self) -> None:
        self.assertNotIn("tenant_id", Product.__table__.columns)
        self.assertNotIn("tenant_id", Price.__table__.columns)
        self.assertIn(
            "ux_billing_product__code",
            {constraint.name for constraint in Product.__table__.constraints},
        )
        self.assertIn(
            "ux_billing_price__product_code",
            {constraint.name for constraint in Price.__table__.constraints},
        )

        product_fk = next(iter(Price.__table__.c.product_id.foreign_keys))
        self.assertTrue(product_fk.target_fullname.endswith(".billing_product.id"))
        self.assertEqual(product_fk.ondelete, "RESTRICT")

    def test_catalog_validation_rejects_tenant_and_normalizes_codes(self) -> None:
        product = BillingProductCreateValidation.model_validate(
            {"Code": "  SKU-One  ", "Name": "  Product One  "}
        )
        self.assertEqual((product.code, product.name), ("SKU-One", "Product One"))

        price = BillingPriceCreateValidation.model_validate(
            {
                "ProductId": str(uuid.uuid4()),
                "Code": "  monthly  ",
                "PriceType": " RECURRING ",
                "Currency": " usd ",
            }
        )
        self.assertEqual(
            (price.code, price.price_type, price.currency),
            ("monthly", "recurring", "USD"),
        )

        for schema, payload in (
            (
                BillingProductCreateValidation,
                {"TenantId": str(uuid.uuid4()), "Code": "x", "Name": "X"},
            ),
            (
                BillingPriceCreateValidation,
                {
                    "tenant_id": str(uuid.uuid4()),
                    "ProductId": str(uuid.uuid4()),
                    "Code": "x",
                    "PriceType": "one_time",
                    "Currency": "USD",
                },
            ),
        ):
            with self.subTest(schema=schema.__name__):
                with self.assertRaisesRegex(ValidationError, "TenantId"):
                    schema.model_validate(payload)

    def test_catalog_update_and_meter_validation(self) -> None:
        for schema, payload in (
            (BillingProductUpdateValidation, {}),
            (BillingProductUpdateValidation, {"Code": None}),
            (BillingPriceUpdateValidation, {}),
            (BillingPriceUpdateValidation, {"ProductId": None}),
            (BillingPriceUpdateValidation, {"Currency": None}),
        ):
            with self.subTest(schema=schema.__name__, payload=payload):
                with self.assertRaises(ValidationError):
                    schema.model_validate(payload)

        with self.assertRaisesRegex(ValidationError, "provided together"):
            BillingPriceCreateValidation.model_validate(
                {
                    "ProductId": str(uuid.uuid4()),
                    "Code": "metered",
                    "PriceType": "metered",
                    "Currency": "USD",
                    "MeterCode": "requests",
                }
            )
        with self.assertRaisesRegex(ValidationError, "require MeterCode"):
            BillingPriceCreateValidation.model_validate(
                {
                    "ProductId": str(uuid.uuid4()),
                    "Code": "metered",
                    "PriceType": "metered",
                    "Currency": "USD",
                }
            )

        with self.assertRaises(ValidationError):
            BillingProductCreateValidation.model_validate(
                {"Code": " ", "Name": "Product"}
            )
        with self.assertRaises(ValidationError):
            BillingProductCreateValidation.model_validate(
                {"Code": "product", "Name": "Product", "Description": " "}
            )

        product_update = BillingProductUpdateValidation.model_validate(
            {
                "Code": " updated ",
                "Name": " Updated Product ",
                "Description": " Details ",
            }
        )
        self.assertEqual(
            (product_update.code, product_update.name, product_update.description),
            ("updated", "Updated Product", "Details"),
        )
        self.assertEqual(
            BillingProductUpdateValidation.model_validate({"Code": " code-only "}).code,
            "code-only",
        )
        self.assertEqual(
            BillingProductUpdateValidation.model_validate({"Name": " Name Only "}).name,
            "Name Only",
        )
        self.assertEqual(
            BillingProductUpdateValidation.model_validate(
                {"Attributes": {}}
            ).attributes,
            {},
        )

        price_update = BillingPriceUpdateValidation.model_validate(
            {
                "ProductId": str(uuid.uuid4()),
                "Code": " updated ",
                "PriceType": " RECURRING ",
                "Currency": " usd ",
                "IntervalUnit": " MONTH ",
                "UsageUnit": " UNIT ",
                "MeterCode": " REQUESTS ",
            }
        )
        self.assertEqual(
            (
                price_update.code,
                price_update.price_type,
                price_update.currency,
                price_update.interval_unit,
                price_update.usage_unit,
                price_update.meter_code,
            ),
            ("updated", "recurring", "USD", "month", "UNIT", "REQUESTS"),
        )
        with self.assertRaises(ValidationError):
            BillingPriceUpdateValidation.model_validate({"IntervalUnit": " "})
        self.assertEqual(
            BillingPriceUpdateValidation.model_validate({"Attributes": {}}).attributes,
            {},
        )

        recurring_meter = BillingPriceCreateValidation.model_validate(
            {
                "ProductId": str(uuid.uuid4()),
                "Code": "usage",
                "PriceType": "recurring",
                "Currency": "USD",
                "IntervalUnit": " MONTH ",
                "UsageUnit": " unit ",
                "MeterCode": " requests ",
            }
        )
        self.assertEqual(recurring_meter.interval_unit, "month")

    def test_contributor_registers_read_only_catalog_role_and_archive_actions(
        self,
    ) -> None:
        admin_ns = AdminNs("com.test.acp")
        plugin_ns = "com.test.billing"
        registry = AdminRegistry(strict_permission_decls=True)
        for verb in ("read", "create", "update", "delete", "manage"):
            registry.register_permission_type(PermissionTypeDef(admin_ns.ns, verb))
        registry.register_global_role(
            GlobalRoleDef(admin_ns.ns, "administrator", "Administrator")
        )

        contribute(
            registry,
            admin_namespace=admin_ns.ns,
            plugin_namespace=plugin_ns,
        )
        manifest = registry.build_seed_manifest()

        self.assertIn(
            f"{plugin_ns}:catalog_reader",
            {role.key for role in manifest.global_roles},
        )
        reader_grants = {
            (grant.permission_object, grant.permission_type)
            for grant in manifest.default_global_grants
            if grant.global_role == f"{plugin_ns}:catalog_reader"
        }
        self.assertEqual(
            reader_grants,
            {
                (f"{plugin_ns}:price", admin_ns.verb("read")),
                (f"{plugin_ns}:product", admin_ns.verb("read")),
            },
        )

        for entity_set in ("BillingProducts", "BillingPrices"):
            resource = registry.get_resource(entity_set)
            self.assertTrue(resource.behavior.resolve_soft_deleted_references)
            self.assertTrue(resource.capabilities.allow_manage)
            self.assertTrue(resource.capabilities.actions["archive"]["is_admin_action"])

    def test_migration_planner_consolidates_identical_rows_and_rejects_conflicts(
        self,
    ) -> None:
        script = r"""
from datetime import datetime, timezone
import importlib
import uuid

module = importlib.import_module(
    "migrations.versions.3e7c9a1b5d2f_global_billing_catalog"
)
tenant_a = uuid.UUID("00000000-0000-0000-0000-00000000000a")
tenant_b = uuid.UUID("00000000-0000-0000-0000-00000000000b")
product_a = uuid.UUID("10000000-0000-0000-0000-000000000001")
product_b = uuid.UUID("10000000-0000-0000-0000-000000000002")
price_a = uuid.UUID("20000000-0000-0000-0000-000000000001")
price_b = uuid.UUID("20000000-0000-0000-0000-000000000002")
created_a = datetime(2025, 1, 1, tzinfo=timezone.utc)
created_b = datetime(2025, 1, 2, tzinfo=timezone.utc)

products = [
    {
        "id": product_a,
        "tenant_id": tenant_a,
        "created_at": created_a,
        "code": " SKU ",
        "name": "Platform SKU",
        "description": "Shared",
        "attributes": None,
        "deleted_at": None,
    },
    {
        "id": product_b,
        "tenant_id": tenant_b,
        "created_at": created_b,
        "code": "sku",
        "name": "Platform SKU",
        "description": "Shared",
        "attributes": {},
        "deleted_at": None,
    },
]
prices = [
    {
        "id": price_a,
        "tenant_id": tenant_a,
        "product_id": product_a,
        "created_at": created_a,
        "code": " MONTHLY ",
        "price_type": "recurring",
        "currency": "USD",
        "unit_amount": 1000,
        "interval_unit": "month",
        "interval_count": 1,
        "trial_period_days": 7,
        "usage_unit": None,
        "meter_code": "legacy-default",
        "attributes": None,
        "deleted_at": None,
    },
    {
        "id": price_b,
        "tenant_id": tenant_b,
        "product_id": product_b,
        "created_at": created_b,
        "code": "monthly",
        "price_type": "recurring",
        "currency": "usd",
        "unit_amount": 1000,
        "interval_unit": "month",
        "interval_count": 1,
        "trial_period_days": 7,
        "usage_unit": None,
        "meter_code": "other-legacy-default",
        "attributes": {},
        "deleted_at": None,
    },
]
product_map, price_map = module._catalog_plan(products, prices)
assert product_map == {product_a: product_a, product_b: product_a}
assert price_map == {price_a: price_a, price_b: price_a}

conflicting_products = [dict(row) for row in products]
conflicting_products[1]["name"] = "Different Product"
try:
    module._catalog_plan(conflicting_products, prices)
except RuntimeError as exc:
    assert "Conflicting Billing Products" in str(exc)
else:
    raise AssertionError("product conflict was not rejected")

conflicting_prices = [dict(row) for row in prices]
conflicting_prices[1]["unit_amount"] = 2000
try:
    module._catalog_plan(products, conflicting_prices)
except RuntimeError as exc:
    assert "Conflicting Billing Prices" in str(exc)
else:
    raise AssertionError("price conflict was not rejected")

private_attributes = [dict(row) for row in products]
private_attributes[0]["attributes"] = {"secret_ref": "local"}
try:
    module._catalog_plan(private_attributes, prices)
except RuntimeError as exc:
    assert str(product_a) in str(exc)
    assert "secret_ref" in str(exc)
else:
    raise AssertionError("non-empty attributes were not rejected")

invalid_meter = [dict(prices[0])]
invalid_meter[0]["price_type"] = "metered"
invalid_meter[0]["usage_unit"] = None
try:
    module._catalog_plan([products[0]], invalid_meter)
except RuntimeError as exc:
    assert "requires MeterCode and UsageUnit" in str(exc)
else:
    raise AssertionError("invalid metered price was not rejected")
"""
        env = dict(os.environ)
        env["MUGEN_ALEMBIC_SCHEMA"] = "mugen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class TestBillingCatalogServices(unittest.IsolatedAsyncioTestCase):
    """Covers catalog normalization, lifecycle, and immutability rules."""

    async def test_product_service_normalizes_create_and_update(self) -> None:
        rsg = _rsg(
            insert_one=AsyncMock(
                return_value={"id": uuid.uuid4(), "code": "SKU", "name": "Name"}
            ),
            update_one=AsyncMock(
                return_value={"id": uuid.uuid4(), "description": "Details"}
            ),
        )
        service = ProductService(table="billing_product", rsg=rsg)

        await service.create({"code": " SKU ", "name": " Name "})
        self.assertEqual(
            rsg.insert_one.await_args.args[1],
            {"code": "SKU", "name": "Name"},
        )
        await service.update({"id": uuid.uuid4()}, {"description": " Details "})
        self.assertEqual(
            rsg.update_one.await_args.kwargs["changes"],
            {"description": "Details"},
        )

    async def test_product_archive_lifecycle_paths(self) -> None:
        service = ProductService(table="billing_product", rsg=_rsg())
        entity_id = uuid.uuid4()
        data = SimpleNamespace(row_version=7)
        common = {
            "entity_id": entity_id,
            "auth_user_id": uuid.uuid4(),
            "data": data,
        }

        service.get = AsyncMock(return_value=None)
        with patch.object(product_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service.entity_action_archive(**common)
        self.assertEqual(raised.exception.code, 404)

        service.get = AsyncMock(
            return_value=ProductDE(
                id=entity_id,
                deleted_at=datetime.now(timezone.utc),
            )
        )
        self.assertEqual(await service.entity_action_archive(**common), ("", 204))

        service.get = AsyncMock(return_value=ProductDE(id=entity_id))
        service.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("billing_product")
        )
        with patch.object(product_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service.entity_action_archive(**common)
        self.assertEqual(raised.exception.code, 409)

        service.update_with_row_version = AsyncMock(
            return_value=ProductDE(id=entity_id)
        )
        self.assertEqual(await service.entity_action_archive(**common), ("", 204))
        changes = service.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["deleted_by_user_id"], common["auth_user_id"])
        self.assertIsNotNone(changes["deleted_at"])

        service.get = AsyncMock(side_effect=SQLAlchemyError("db"))
        with patch.object(product_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service.entity_action_archive(**common)
        self.assertEqual(raised.exception.code, 500)

        service.get = AsyncMock(return_value=ProductDE(id=entity_id))
        service.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
        with patch.object(product_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service.entity_action_archive(**common)
        self.assertEqual(raised.exception.code, 500)

        service.update_with_row_version = AsyncMock(return_value=None)
        with patch.object(product_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service.entity_action_archive(**common)
        self.assertEqual(raised.exception.code, 404)

    async def test_product_row_version_update_normalizes_values(self) -> None:
        rsg = _rsg(
            update_one=AsyncMock(return_value={"id": uuid.uuid4(), "code": "updated"})
        )
        service = ProductService(table="billing_product", rsg=rsg)
        await service.update_with_row_version(
            {"id": uuid.uuid4()},
            expected_row_version=2,
            changes={"code": " updated "},
        )
        self.assertEqual(
            rsg.update_one.await_args.kwargs["changes"],
            {"code": "updated"},
        )

    async def test_price_service_create_and_immutability(self) -> None:
        rsg = _rsg(
            insert_one=AsyncMock(return_value={"id": uuid.uuid4()}),
            update_one=AsyncMock(return_value={"id": uuid.uuid4(), "code": "new"}),
        )
        service = PriceService(table="billing_price", rsg=rsg)
        product_id = uuid.uuid4()
        price_id = uuid.uuid4()
        service._product_service.get = AsyncMock(  # pylint: disable=protected-access
            return_value=ProductDE(id=product_id)
        )

        await service.create(
            {
                "product_id": product_id,
                "code": " Price ",
                "price_type": " ONE_TIME ",
                "currency": " usd ",
            }
        )
        payload = rsg.insert_one.await_args.args[1]
        self.assertEqual(
            (payload["code"], payload["price_type"], payload["currency"]),
            ("Price", "one_time", "USD"),
        )

        current = PriceDE(
            id=price_id,
            product_id=product_id,
            code="old",
            price_type="one_time",
            currency="USD",
        )
        service.get = AsyncMock(return_value=current)
        service._is_referenced = AsyncMock(
            return_value=True
        )  # pylint: disable=protected-access
        with patch.object(price_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service.update(
                    {"id": price_id},
                    {"unit_amount": 1500},
                )
        self.assertEqual(raised.exception.code, 409)
        self.assertIn("new Price", raised.exception.message)

        await service.update({"id": price_id}, {"code": " new "})
        self.assertEqual(
            rsg.update_one.await_args.kwargs["changes"],
            {"code": "new"},
        )

    async def test_price_reference_scan_and_meter_contract(self) -> None:
        rsg = _rsg(count_many=AsyncMock(side_effect=[0, 0, 1]))
        service = PriceService(table="billing_price", rsg=rsg)
        self.assertTrue(
            await service._is_referenced(uuid.uuid4())
        )  # pylint: disable=protected-access
        self.assertEqual(rsg.count_many.await_count, 3)

        service._product_service.get = AsyncMock(
            return_value=None
        )  # pylint: disable=protected-access
        with patch.object(price_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service.create(
                    {
                        "product_id": uuid.uuid4(),
                        "code": "x",
                        "price_type": "one_time",
                        "currency": "USD",
                    }
                )
        self.assertEqual(raised.exception.code, 400)

        rsg.count_many = AsyncMock(return_value=0)
        self.assertFalse(  # pylint: disable=protected-access
            await service._is_referenced(uuid.uuid4())
        )

        with patch.object(price_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                service._validate_meter_contract(  # pylint: disable=protected-access
                    {"price_type": "metered"}
                )
        self.assertEqual(raised.exception.code, 400)

    async def test_price_update_paths(self) -> None:
        rsg = _rsg(
            update_one=AsyncMock(return_value={"id": uuid.uuid4(), "unit_amount": 2})
        )
        service = PriceService(table="billing_price", rsg=rsg)
        price_id = uuid.uuid4()
        product_id = uuid.uuid4()
        replacement_product_id = uuid.uuid4()
        current = PriceDE(
            id=price_id,
            product_id=product_id,
            code="base",
            price_type="one_time",
            currency="USD",
            unit_amount=1,
        )

        service.get = AsyncMock(return_value=None)
        self.assertIsNone(await service.update({"id": price_id}, {"code": "new"}))
        self.assertIsNone(
            await service.update_with_row_version(
                {"id": price_id},
                expected_row_version=1,
                changes={"code": "new"},
            )
        )

        service.get = AsyncMock(return_value=current)
        service._is_referenced = AsyncMock(
            return_value=False
        )  # pylint: disable=protected-access
        service._product_service.get = AsyncMock(  # pylint: disable=protected-access
            return_value=ProductDE(id=replacement_product_id)
        )
        await service.update_with_row_version(
            {"id": price_id},
            expected_row_version=1,
            changes={"product_id": replacement_product_id, "unit_amount": 2},
        )
        service._product_service.get.assert_awaited_once()  # pylint: disable=protected-access

        transient = PriceDE(
            product_id=product_id,
            code="base",
            price_type="one_time",
            currency="USD",
            unit_amount=1,
        )
        service._is_referenced.reset_mock()  # pylint: disable=protected-access
        await service._validate_update(  # pylint: disable=protected-access
            transient,
            {"unit_amount": 2},
        )
        service._is_referenced.assert_not_awaited()  # pylint: disable=protected-access

        with patch.object(price_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                service._validate_meter_contract(  # pylint: disable=protected-access
                    {"price_type": "metered", "meter_code": "requests"}
                )
        self.assertEqual(raised.exception.code, 400)

    async def test_price_archive_success(self) -> None:
        service = PriceService(table="billing_price", rsg=_rsg())
        price_id = uuid.uuid4()
        service.get = AsyncMock(return_value=PriceDE(id=price_id))
        service.update_with_row_version = AsyncMock(return_value=PriceDE(id=price_id))
        result = await service.entity_action_archive(
            entity_id=price_id,
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(row_version=3),
        )
        self.assertEqual(result, ("", 204))

    async def test_price_archive_error_and_idempotent_paths(self) -> None:
        service = PriceService(table="billing_price", rsg=_rsg())
        price_id = uuid.uuid4()
        common = {
            "entity_id": price_id,
            "auth_user_id": uuid.uuid4(),
            "data": SimpleNamespace(row_version=3),
        }

        scenarios = (
            (SQLAlchemyError("db"), 500),
            (None, 404),
        )
        for current, status_code in scenarios:
            service.get = AsyncMock(
                side_effect=current if isinstance(current, Exception) else None,
                return_value=current,
            )
            with self.subTest(status_code=status_code):
                with patch.object(price_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as raised:
                        await service.entity_action_archive(**common)
                self.assertEqual(raised.exception.code, status_code)

        service.get = AsyncMock(
            return_value=PriceDE(
                id=price_id,
                deleted_at=datetime.now(timezone.utc),
            )
        )
        self.assertEqual(await service.entity_action_archive(**common), ("", 204))

        service.get = AsyncMock(return_value=PriceDE(id=price_id))
        for failure, status_code in (
            (RowVersionConflict("billing_price"), 409),
            (SQLAlchemyError("db"), 500),
            (None, 404),
        ):
            service.update_with_row_version = AsyncMock(
                side_effect=failure if isinstance(failure, Exception) else None,
                return_value=failure,
            )
            with self.subTest(update_status=status_code):
                with patch.object(price_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as raised:
                        await service.entity_action_archive(**common)
                self.assertEqual(raised.exception.code, status_code)


class TestBillingSubscriptionCatalogValidation(unittest.IsolatedAsyncioTestCase):
    """Covers tenant isolation, catalog availability, and meter matching."""

    def _service(self) -> SubscriptionService:
        service = SubscriptionService(table="billing_subscription", rsg=_rsg())
        service._account_service.get = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        service._price_service.get = AsyncMock(  # pylint: disable=protected-access
            return_value=PriceDE(
                id=uuid.uuid4(),
                product_id=uuid.uuid4(),
                price_type="one_time",
            )
        )
        service._product_service.get = AsyncMock(  # pylint: disable=protected-access
            return_value=ProductDE(id=uuid.uuid4())
        )
        service._meter_definition_service.list = AsyncMock(
            return_value=[]
        )  # pylint: disable=protected-access
        return service

    async def test_cross_tenant_or_unavailable_catalog_selection_is_rejected(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        account_id = uuid.uuid4()
        price_id = uuid.uuid4()
        common = {
            "tenant_id": tenant_id,
            "account_id": account_id,
            "price_id": price_id,
            "status_code": 400,
        }

        for missing_service, expected_message in (
            ("_account_service", "route tenant"),
            ("_price_service", "global Price"),
            ("_product_service", "Product is not available"),
        ):
            service = self._service()
            getattr(service, missing_service).get = AsyncMock(return_value=None)
            with self.subTest(missing_service=missing_service):
                with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
                    with self.assertRaises(_AbortCalled) as raised:
                        await service._validate_catalog_selection(  # pylint: disable=protected-access
                            **common
                        )
                self.assertEqual(raised.exception.code, 400)
                self.assertIn(expected_message, raised.exception.message)

        service = self._service()
        await service._validate_catalog_selection(
            **common
        )  # pylint: disable=protected-access
        self.assertEqual(
            service._account_service.get.await_args.args[
                0
            ],  # pylint: disable=protected-access
            {
                "id": account_id,
                "tenant_id": tenant_id,
                "deleted_at": None,
            },
        )

    async def test_meter_definition_matching_is_normalized_and_unit_safe(self) -> None:
        service = self._service()
        tenant_id = uuid.uuid4()
        price = PriceDE(
            id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            price_type="metered",
            meter_code=" Requests ",
            usage_unit=" UNIT ",
        )
        service._price_service.get = AsyncMock(
            return_value=price
        )  # pylint: disable=protected-access
        common = {
            "tenant_id": tenant_id,
            "account_id": uuid.uuid4(),
            "price_id": price.id,
            "status_code": 409,
        }

        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service._validate_catalog_selection(
                    **common
                )  # pylint: disable=protected-access
        self.assertEqual(raised.exception.code, 409)
        self.assertIn("matching active", raised.exception.message)

        service._meter_definition_service.list = (
            AsyncMock(  # pylint: disable=protected-access
                return_value=[
                    SimpleNamespace(code="requests", unit="minute"),
                ]
            )
        )
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service._validate_catalog_selection(
                    **common
                )  # pylint: disable=protected-access
        self.assertIn("unit must match", raised.exception.message)

        service._meter_definition_service.list = (
            AsyncMock(  # pylint: disable=protected-access
                return_value=[
                    SimpleNamespace(code=" requests ", unit=" unit "),
                ]
            )
        )
        await service._validate_catalog_selection(
            **common
        )  # pylint: disable=protected-access

        service._meter_definition_service.list = (
            AsyncMock(  # pylint: disable=protected-access
                return_value=[
                    SimpleNamespace(code="requests", unit="unit"),
                    SimpleNamespace(code=" REQUESTS ", unit="unit"),
                ]
            )
        )
        with patch.object(subscription_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as raised:
                await service._validate_catalog_selection(
                    **common
                )  # pylint: disable=protected-access
        self.assertIn("multiple normalized", raised.exception.message)

    async def test_two_tenants_can_create_against_same_global_price(self) -> None:
        service = self._service()
        price_id = (
            service._price_service.get.return_value.id
        )  # pylint: disable=protected-access
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()

        for tenant_id in (tenant_a, tenant_b):
            await service.create(
                {
                    "tenant_id": tenant_id,
                    "account_id": uuid.uuid4(),
                    "price_id": price_id,
                }
            )

        account_wheres = [
            call.args[0]
            for call in service._account_service.get.await_args_list  # pylint: disable=protected-access
        ]
        self.assertEqual(
            {where["tenant_id"] for where in account_wheres},
            {tenant_a, tenant_b},
        )
        price_wheres = [
            call.args[0]
            for call in service._price_service.get.await_args_list  # pylint: disable=protected-access
        ]
        self.assertEqual({where["id"] for where in price_wheres}, {price_id})


if __name__ == "__main__":
    unittest.main()
