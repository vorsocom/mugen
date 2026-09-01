"""Tests Core Service Profile resources, lifecycles, and runtime contracts."""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

import mugen.core.plugin.service_profile.fw_ext as fw_ext_module
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.contract.service.service_profile import (
    ServiceProfileEntitlementReason,
    ServiceProfileResolutionReason,
)
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.service_profile.api.validation import (
    ServiceProfileCreateValidation,
    ServiceProfileSubscriptionCreateValidation,
    ServiceProfileUpdateValidation,
)
from mugen.core.plugin.service_profile.contrib import contribute
from mugen.core.plugin.service_profile.domain import (
    ServiceProfileDE,
    ServiceProfileIngressBindingDE,
    ServiceProfileSubscriptionDE,
)
from mugen.core.plugin.service_profile.fw_ext import ServiceProfileFWExtension
from mugen.core.plugin.service_profile.model import (
    ServiceProfile,
    ServiceProfileIngressBinding,
    ServiceProfileSubscription,
)
from mugen.core.plugin.service_profile.service.commercial import (
    CommercialValidationError,
    load_commercial_contract,
    normalize_product_code,
)
from mugen.core.plugin.service_profile.service.runtime import (
    DefaultServiceProfileEntitlementService,
    DefaultServiceProfileResolver,
)
from mugen.core.plugin.service_profile.service.service_profile import (
    ServiceProfileService,
)
from mugen.core.plugin.service_profile.service.service_profile_ingress_binding import (
    ServiceProfileIngressBindingService,
)
from mugen.core.plugin.service_profile.service.service_profile_subscription import (
    ServiceProfileSubscriptionService,
)


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestServiceProfileSurface(unittest.TestCase):
    """Validate ACP registration, immutable payloads, and relational metadata."""

    def test_models_and_validation_contracts(self) -> None:
        self.assertEqual(
            ServiceProfile.__tablename__, "service_profile_service_profile"
        )
        self.assertIn("service_profile_id", ServiceProfileIngressBinding.__table__.c)
        self.assertIn("product_code", ServiceProfileSubscription.__table__.c)
        self.assertIn(
            "ux_service_profile_subscription__tenant_id_id",
            {item.name for item in ServiceProfileSubscription.__table__.constraints},
        )
        self.assertIn(
            "ServiceProfile(id=",
            ServiceProfile.__repr__(SimpleNamespace(id=None)),
        )
        self.assertIn(
            "ServiceProfileIngressBinding(id=",
            ServiceProfileIngressBinding.__repr__(SimpleNamespace(id=None)),
        )
        self.assertIn(
            "ServiceProfileSubscription(id=",
            ServiceProfileSubscription.__repr__(SimpleNamespace(id=None)),
        )

        tenant_id = uuid.uuid4()
        created = ServiceProfileCreateValidation.model_validate(
            {
                "TenantId": str(tenant_id),
                "Key": "primary",
                "DisplayName": "Primary",
            }
        )
        self.assertEqual(created.tenant_id, tenant_id)
        updated = ServiceProfileUpdateValidation.model_validate(
            {"RowVersion": 1, "DisplayName": "Updated"}
        )
        self.assertEqual(updated.display_name, "Updated")
        with self.assertRaises(ValidationError):
            ServiceProfileUpdateValidation.model_validate(
                {"RowVersion": 1, "Key": "immutable"}
            )
        with self.assertRaises(ValidationError):
            ServiceProfileSubscriptionCreateValidation.model_validate(
                {
                    "TenantId": str(tenant_id),
                    "ServiceProfileId": str(uuid.uuid4()),
                    "BillingSubscriptionId": str(uuid.uuid4()),
                    "ProductCode": "client-forbidden",
                }
            )
        valid_assignment = ServiceProfileSubscriptionCreateValidation.model_validate(
            {
                "TenantId": str(tenant_id),
                "ServiceProfileId": str(uuid.uuid4()),
                "BillingSubscriptionId": str(uuid.uuid4()),
            }
        )
        self.assertEqual(valid_assignment.tenant_id, tenant_id)

    def test_contribution_binds_read_only_delete_policy_and_admin_grants(self) -> None:
        admin_ns = AdminNs("com.test.admin")
        registry = AdminRegistry(strict_permission_decls=True)
        for verb in ("read", "create", "update", "delete", "manage"):
            registry.register_permission_type(PermissionTypeDef(admin_ns.ns, verb))
        registry.register_global_role(
            GlobalRoleDef(
                namespace=admin_ns.ns,
                name="administrator",
                display_name="Administrator",
            )
        )
        contribute(
            registry,
            admin_namespace=admin_ns.ns,
            plugin_namespace="com.test.service_profile",
        )
        rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=rsg).bind_all()
        registry.freeze()

        expected_services = {
            "ServiceProfiles": ServiceProfileService,
            "ServiceProfileIngressBindings": ServiceProfileIngressBindingService,
            "ServiceProfileSubscriptions": ServiceProfileSubscriptionService,
        }
        for entity_set, service_type in expected_services.items():
            resource = registry.get_resource(entity_set)
            self.assertFalse(resource.capabilities.allow_delete)
            self.assertIsInstance(
                registry.get_edm_service(resource.service_key), service_type
            )
        self.assertIn(
            "activate",
            registry.get_resource("ServiceProfiles").capabilities.actions,
        )
        self.assertNotIn(
            "activate",
            registry.get_resource("ServiceProfileIngressBindings").capabilities.actions,
        )
        manifest = registry.build_seed_manifest()
        profile_object = "com.test.service_profile:service_profile"
        grants = [
            grant
            for grant in manifest.default_global_grants
            if grant.permission_object == profile_object
        ]
        self.assertEqual(len(grants), 4)
        self.assertTrue(
            all(grant.global_role == admin_ns.key("administrator") for grant in grants)
        )


class TestServiceProfileCrudServices(unittest.IsolatedAsyncioTestCase):
    """Exercise profile and ingress-assignment lifecycle behavior."""

    async def test_profile_normalization_update_and_lifecycle(self) -> None:
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        service = ServiceProfileService("profiles", Mock())
        created = ServiceProfileDE(id=profile_id, tenant_id=tenant_id)
        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=created),
        ) as base_create:
            self.assertIs(
                await service.create(
                    {
                        "tenant_id": tenant_id,
                        "key": "  MAIN-Customer-Service  ",
                        "display_name": "  Main Customer Service  ",
                    }
                ),
                created,
            )
        payload = base_create.await_args.args[0]
        self.assertEqual(payload["key"], "main-customer-service")
        self.assertEqual(payload["display_name"], "Main Customer Service")
        self.assertEqual(payload["status"], "draft")

        with self.assertRaises(HTTPException) as context:
            await service.create(
                {"tenant_id": tenant_id, "key": " ", "display_name": "x"}
            )
        self.assertEqual(context.exception.code, 400)
        with self.assertRaises(HTTPException):
            ServiceProfileService._normalize_display_name(" ")

        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(return_value=created),
        ) as base_update:
            await service.update_with_row_version(
                {"id": profile_id},
                expected_row_version=1,
                changes={"display_name": "  New Name  ", "attributes": {}},
            )
        self.assertEqual(
            base_update.await_args.kwargs["changes"]["display_name"], "New Name"
        )
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(return_value=created),
        ) as base_update:
            await service.update_with_row_version(
                {"id": profile_id},
                expected_row_version=1,
                changes={"attributes": {"tier": "gold"}},
            )
        self.assertEqual(
            base_update.await_args.kwargs["changes"],
            {"attributes": {"tier": "gold"}},
        )

        current = ServiceProfileDE(
            id=profile_id,
            tenant_id=tenant_id,
            row_version=2,
            status="draft",
        )
        service._get_for_action = AsyncMock(return_value=current)
        service._has_valid_ingress_assignment = AsyncMock(return_value=False)
        with self.assertRaises(HTTPException) as context:
            await service.action_activate(
                tenant_id=tenant_id,
                entity_id=profile_id,
                where={"tenant_id": tenant_id, "id": profile_id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=2),
            )
        self.assertEqual(context.exception.code, 409)
        service._has_valid_ingress_assignment = AsyncMock(return_value=True)
        service.update_with_row_version = AsyncMock(return_value=current)
        result = await service.action_activate(
            tenant_id=tenant_id,
            entity_id=profile_id,
            where={"tenant_id": tenant_id, "id": profile_id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=2),
        )
        self.assertEqual(result, ("", 204))
        changes = service.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "active")
        self.assertIsNotNone(changes["activated_at"])

        current.status = "active"
        service.update_with_row_version = AsyncMock(return_value=current)
        await service.action_disable(
            tenant_id=tenant_id,
            entity_id=profile_id,
            where={"tenant_id": tenant_id, "id": profile_id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=2),
        )
        self.assertEqual(
            service.update_with_row_version.await_args.kwargs["changes"]["status"],
            "disabled",
        )

    async def test_profile_action_helpers_and_ingress_eligibility(self) -> None:
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        binding_id = uuid.uuid4()
        rsg = Mock()
        rsg.find_many = AsyncMock(
            return_value=[
                {"ingress_binding_id": uuid.uuid4()},
                {"ingress_binding_id": binding_id},
            ]
        )
        rsg.get_one = AsyncMock(side_effect=[None, {"id": binding_id}])
        service = ServiceProfileService("profiles", rsg)
        self.assertTrue(
            await service._has_valid_ingress_assignment(
                tenant_id=tenant_id,
                service_profile_id=profile_id,
            )
        )
        rsg.find_many = AsyncMock(return_value=[])
        self.assertFalse(
            await service._has_valid_ingress_assignment(
                tenant_id=tenant_id,
                service_profile_id=profile_id,
            )
        )

        current = ServiceProfileDE(id=profile_id, row_version=1, status="draft")
        service.get = AsyncMock(return_value=current)
        self.assertIs(
            await service._get_for_action(
                where={"id": profile_id}, expected_row_version=1
            ),
            current,
        )
        service.get = AsyncMock(side_effect=[None, current])
        with self.assertRaises(HTTPException) as context:
            await service._get_for_action(
                where={"id": profile_id}, expected_row_version=2
            )
        self.assertEqual(context.exception.code, 409)
        service.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as context:
            await service._get_for_action(
                where={"id": profile_id}, expected_row_version=2
            )
        self.assertEqual(context.exception.code, 404)
        service.get = AsyncMock(side_effect=SQLAlchemyError("db"))
        with self.assertRaises(HTTPException) as context:
            await service._get_for_action(
                where={"id": profile_id}, expected_row_version=2
            )
        self.assertEqual(context.exception.code, 500)

        service._get_for_action = AsyncMock(return_value=current)
        service.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict("profiles")
        )
        with self.assertRaises(HTTPException) as context:
            await service._transition(
                where={"id": profile_id},
                expected_row_version=1,
                from_status="draft",
                changes={"status": "active"},
            )
        self.assertEqual(context.exception.code, 409)
        service.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
        with self.assertRaises(HTTPException) as context:
            await service._transition(
                where={"id": profile_id},
                expected_row_version=1,
                from_status="draft",
                changes={"status": "active"},
            )
        self.assertEqual(context.exception.code, 500)
        service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as context:
            await service._transition(
                where={"id": profile_id},
                expected_row_version=1,
                from_status="draft",
                changes={"status": "active"},
            )
        self.assertEqual(context.exception.code, 404)
        current.status = "active"
        with self.assertRaises(HTTPException) as context:
            await service._transition(
                where={"id": profile_id},
                expected_row_version=1,
                from_status="draft",
                changes={"status": "active"},
            )
        self.assertEqual(context.exception.code, 409)

        service._get_for_action = AsyncMock(return_value=current)
        with self.assertRaises(HTTPException) as context:
            await service.action_activate(
                tenant_id=tenant_id,
                entity_id=profile_id,
                where={"id": profile_id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=1),
            )
        self.assertEqual(context.exception.code, 409)
        current.status = "draft"
        service._has_valid_ingress_assignment = AsyncMock(
            side_effect=SQLAlchemyError("db")
        )
        with self.assertRaises(HTTPException) as context:
            await service.action_activate(
                tenant_id=tenant_id,
                entity_id=profile_id,
                where={"id": profile_id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=1),
            )
        self.assertEqual(context.exception.code, 500)

    async def test_ingress_assignment_reference_validation_and_reactivation(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        binding_id = uuid.uuid4()
        rsg = Mock()
        rsg.get_one = AsyncMock(side_effect=[{"status": "draft"}, {"is_active": True}])
        service = ServiceProfileIngressBindingService("assignments", rsg)
        created = ServiceProfileIngressBindingDE(id=uuid.uuid4(), tenant_id=tenant_id)
        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=created),
        ) as base_create:
            result = await service.create(
                {
                    "tenant_id": tenant_id,
                    "service_profile_id": profile_id,
                    "ingress_binding_id": binding_id,
                }
            )
        self.assertIs(result, created)
        self.assertTrue(base_create.await_args.args[0]["is_active"])

        rsg.get_one = AsyncMock(side_effect=[None, {"is_active": True}])
        with self.assertRaises(HTTPException) as context:
            await service._validate_references(
                {
                    "tenant_id": tenant_id,
                    "service_profile_id": profile_id,
                    "ingress_binding_id": binding_id,
                }
            )
        self.assertEqual(context.exception.code, 400)
        rsg.get_one = AsyncMock(side_effect=[{"status": "draft"}, None])
        with self.assertRaises(HTTPException) as context:
            await service._validate_references(
                {
                    "tenant_id": tenant_id,
                    "service_profile_id": profile_id,
                    "ingress_binding_id": binding_id,
                }
            )
        self.assertEqual(context.exception.code, 400)
        rsg.get_one = AsyncMock(side_effect=SQLAlchemyError("db"))
        with self.assertRaises(HTTPException) as context:
            await service._validate_references({"tenant_id": tenant_id})
        self.assertEqual(context.exception.code, 500)

        current = ServiceProfileIngressBindingDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            service_profile_id=profile_id,
            ingress_binding_id=binding_id,
        )
        service.get = AsyncMock(return_value=None)
        self.assertIsNone(
            await service.update_with_row_version(
                {"id": current.id},
                expected_row_version=1,
                changes={"is_active": True},
            )
        )
        service.get = AsyncMock(return_value=current)
        service._validate_references = AsyncMock()
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(return_value=current),
        ):
            await service.update_with_row_version(
                {"id": current.id},
                expected_row_version=1,
                changes={"is_active": True},
            )
        service._validate_references.assert_awaited_once()
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(return_value=current),
        ) as base_update:
            await service.update_with_row_version(
                {"id": current.id},
                expected_row_version=1,
                changes={"is_active": False},
            )
        base_update.assert_awaited_once()


class TestServiceProfileCommercial(unittest.IsolatedAsyncioTestCase):
    """Validate Billing allocation boundaries and exact entitlement provenance."""

    def setUp(self) -> None:
        self.now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        self.tenant_id = uuid.uuid4()
        self.profile_id = uuid.uuid4()
        self.subscription_id = uuid.uuid4()
        self.account_id = uuid.uuid4()
        self.price_id = uuid.uuid4()
        self.product_id = uuid.uuid4()

    def _rows(self) -> dict[str, dict]:
        return {
            "service_profile_service_profile": {
                "id": self.profile_id,
                "tenant_id": self.tenant_id,
                "status": "active",
                "deleted_at": None,
            },
            "billing_subscription": {
                "id": self.subscription_id,
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "price_id": self.price_id,
                "status": "trialing",
                "started_at": self.now - timedelta(days=2),
                "current_period_start": self.now - timedelta(days=1),
                "current_period_end": self.now + timedelta(days=1),
                "cancel_at": self.now + timedelta(hours=1),
                "canceled_at": None,
                "ended_at": None,
                "deleted_at": None,
            },
            "billing_account": {
                "id": self.account_id,
                "tenant_id": self.tenant_id,
                "deleted_at": None,
            },
            "billing_price": {
                "id": self.price_id,
                "product_id": self.product_id,
                "deleted_at": None,
            },
            "billing_product": {
                "id": self.product_id,
                "code": "  Support.PRO  ",
                "deleted_at": None,
            },
        }

    @staticmethod
    def _rsg(rows: dict[str, dict]) -> Mock:
        rsg = Mock()

        async def get_one(table, where):
            row = rows.get(table)
            if row is None:
                return None
            if any(row.get(key) != value for key, value in where.items()):
                return None
            return row

        rsg.get_one = AsyncMock(side_effect=get_one)
        return rsg

    async def test_commercial_contract_success_and_normalization(self) -> None:
        self.assertEqual(normalize_product_code("  SUPPORT.Pro "), "support.pro")
        with self.assertRaises(CommercialValidationError):
            normalize_product_code(" ")
        contract = await load_commercial_contract(
            self._rsg(self._rows()),
            tenant_id=self.tenant_id,
            service_profile_id=self.profile_id,
            billing_subscription_id=self.subscription_id,
            now=self.now,
            require_profile_active=True,
        )
        self.assertEqual(contract.product_code, "support.pro")
        self.assertEqual(contract.subscription["id"], self.subscription_id)

    async def test_commercial_contract_rejects_invalid_graph_states(self) -> None:
        scenarios = (
            (
                "service_profile_service_profile",
                "status",
                "draft",
                ServiceProfileEntitlementReason.INACTIVE_PROFILE,
            ),
            (
                "billing_subscription",
                "status",
                "paused",
                ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            ),
            (
                "billing_subscription",
                "started_at",
                self.now + timedelta(seconds=1),
                ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            ),
            (
                "billing_subscription",
                "current_period_start",
                None,
                ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            ),
            (
                "billing_subscription",
                "current_period_end",
                self.now,
                ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            ),
            (
                "billing_subscription",
                "cancel_at",
                self.now,
                ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            ),
            (
                "billing_subscription",
                "canceled_at",
                self.now,
                ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            ),
            (
                "billing_subscription",
                "ended_at",
                self.now,
                ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
            ),
            (
                "billing_account",
                "deleted_at",
                self.now,
                ServiceProfileEntitlementReason.INACTIVE_ACCOUNT,
            ),
            (
                "billing_price",
                "deleted_at",
                self.now,
                ServiceProfileEntitlementReason.INACTIVE_PRICE,
            ),
            (
                "billing_product",
                "deleted_at",
                self.now,
                ServiceProfileEntitlementReason.INACTIVE_PRODUCT,
            ),
            (
                "billing_product",
                "code",
                " ",
                ServiceProfileEntitlementReason.INACTIVE_PRODUCT,
            ),
        )
        for table, field, value, reason in scenarios:
            with self.subTest(table=table, field=field):
                rows = self._rows()
                rows[table][field] = value
                with self.assertRaises(CommercialValidationError) as context:
                    await load_commercial_contract(
                        self._rsg(rows),
                        tenant_id=self.tenant_id,
                        service_profile_id=self.profile_id,
                        billing_subscription_id=self.subscription_id,
                        now=self.now.replace(tzinfo=None),
                        require_profile_active=True,
                    )
                self.assertEqual(context.exception.reason, reason)

    async def test_subscription_create_activate_disable_and_uniqueness(self) -> None:
        rows = self._rows()
        current_time = datetime.now(timezone.utc)
        rows["billing_subscription"].update(
            {
                "started_at": current_time - timedelta(days=2),
                "current_period_start": current_time - timedelta(days=1),
                "current_period_end": current_time + timedelta(days=1),
                "cancel_at": current_time + timedelta(hours=1),
            }
        )
        rsg = self._rsg(rows)
        service = ServiceProfileSubscriptionService("assignments", rsg)
        assignment = ServiceProfileSubscriptionDE(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            service_profile_id=self.profile_id,
            billing_subscription_id=self.subscription_id,
            row_version=1,
            status="draft",
        )
        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=assignment),
        ) as base_create:
            self.assertIs(
                await service.create(
                    {
                        "tenant_id": self.tenant_id,
                        "service_profile_id": self.profile_id,
                        "billing_subscription_id": self.subscription_id,
                        "product_code": "forbidden",
                    }
                ),
                assignment,
            )
        self.assertIsNone(base_create.await_args.args[0]["product_code"])

        service._get_for_action = AsyncMock(return_value=assignment)
        service._assert_allocation_available = AsyncMock()
        service.update_with_row_version = AsyncMock(return_value=assignment)
        result = await service.action_activate(
            tenant_id=self.tenant_id,
            entity_id=assignment.id,
            where={"tenant_id": self.tenant_id, "id": assignment.id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=1),
        )
        self.assertEqual(result, ("", 204))
        changes = service.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["product_code"], "support.pro")

        assignment.status = "active"
        service.update_with_row_version = AsyncMock(return_value=assignment)
        await service.action_disable(
            tenant_id=self.tenant_id,
            entity_id=assignment.id,
            where={"tenant_id": self.tenant_id, "id": assignment.id},
            auth_user_id=uuid.uuid4(),
            data=RowVersionValidation(row_version=1),
        )
        self.assertEqual(
            service.update_with_row_version.await_args.kwargs["changes"]["status"],
            "disabled",
        )

        rsg.find_many = AsyncMock(
            side_effect=[
                [{"id": uuid.uuid4()}],
                [],
            ]
        )
        uniqueness_service = ServiceProfileSubscriptionService("assignments", rsg)
        with self.assertRaises(HTTPException) as context:
            await uniqueness_service._assert_allocation_available(
                tenant_id=self.tenant_id,
                assignment_id=assignment.id,
                service_profile_id=self.profile_id,
                billing_subscription_id=self.subscription_id,
                product_code="support.pro",
            )
        self.assertEqual(context.exception.code, 409)

    async def test_subscription_action_failure_paths(self) -> None:
        service = ServiceProfileSubscriptionService("assignments", Mock())
        assignment = ServiceProfileSubscriptionDE(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            row_version=1,
            status="active",
        )
        service._get_for_action = AsyncMock(return_value=assignment)
        with self.assertRaises(HTTPException) as context:
            await service.action_activate(
                tenant_id=self.tenant_id,
                entity_id=assignment.id,
                where={"id": assignment.id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=1),
            )
        self.assertEqual(context.exception.code, 409)

        assignment.status = "draft"
        with self.assertRaises(HTTPException):
            await service.action_activate(
                tenant_id=self.tenant_id,
                entity_id=assignment.id,
                where={"id": assignment.id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=1),
            )

    async def test_subscription_helpers_cover_reference_and_storage_failures(
        self,
    ) -> None:
        service = ServiceProfileSubscriptionService("assignments", Mock())
        payload = {
            "tenant_id": self.tenant_id,
            "service_profile_id": self.profile_id,
            "billing_subscription_id": self.subscription_id,
        }
        service._rsg.get_one = AsyncMock(
            side_effect=[None, {"id": self.subscription_id}]
        )
        with self.assertRaises(HTTPException) as context:
            await service.create(payload)
        self.assertEqual(context.exception.code, 400)
        service._rsg.get_one = AsyncMock(side_effect=[{"status": "draft"}, None])
        with self.assertRaises(HTTPException) as context:
            await service.create(payload)
        self.assertEqual(context.exception.code, 400)
        service._rsg.get_one = AsyncMock(side_effect=SQLAlchemyError("db"))
        with self.assertRaises(HTTPException) as context:
            await service.create(payload)
        self.assertEqual(context.exception.code, 500)

        current = ServiceProfileSubscriptionDE(id=uuid.uuid4(), row_version=1)
        service.get = AsyncMock(return_value=current)
        self.assertIs(
            await service._get_for_action(
                where={"id": current.id}, expected_row_version=1
            ),
            current,
        )
        service.get = AsyncMock(side_effect=[None, current])
        with self.assertRaises(HTTPException) as context:
            await service._get_for_action(
                where={"id": current.id}, expected_row_version=2
            )
        self.assertEqual(context.exception.code, 409)
        service.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as context:
            await service._get_for_action(
                where={"id": current.id}, expected_row_version=2
            )
        self.assertEqual(context.exception.code, 404)
        service.get = AsyncMock(side_effect=SQLAlchemyError("db"))
        with self.assertRaises(HTTPException) as context:
            await service._get_for_action(
                where={"id": current.id}, expected_row_version=2
            )
        self.assertEqual(context.exception.code, 500)

        for effect, expected in (
            (RowVersionConflict("assignments"), 409),
            (SQLAlchemyError("db"), 500),
            (None, 404),
        ):
            with self.subTest(expected=expected):
                service.update_with_row_version = AsyncMock(
                    side_effect=effect if isinstance(effect, Exception) else None,
                    return_value=effect,
                )
                with self.assertRaises(HTTPException) as context:
                    await service._update_action(
                        where={"id": current.id},
                        expected_row_version=1,
                        changes={"status": "active"},
                    )
                self.assertEqual(context.exception.code, expected)

        service._rsg.find_many = AsyncMock(
            side_effect=[[{"id": current.id}], [{"id": uuid.uuid4()}]]
        )
        with self.assertRaises(HTTPException) as context:
            await service._assert_allocation_available(
                tenant_id=self.tenant_id,
                assignment_id=current.id,
                service_profile_id=self.profile_id,
                billing_subscription_id=self.subscription_id,
                product_code="support.pro",
            )
        self.assertEqual(context.exception.code, 409)

        service._rsg.find_many = AsyncMock(side_effect=[[], []])
        await service._assert_allocation_available(
            tenant_id=self.tenant_id,
            assignment_id=current.id,
            service_profile_id=self.profile_id,
            billing_subscription_id=self.subscription_id,
            product_code="support.pro",
        )

        current.status = "draft"
        current.service_profile_id = self.profile_id
        current.billing_subscription_id = self.subscription_id
        service._get_for_action = AsyncMock(return_value=current)
        with patch(
            "mugen.core.plugin.service_profile.service."
            "service_profile_subscription.load_commercial_contract",
            new=AsyncMock(
                side_effect=CommercialValidationError(
                    ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
                    "inactive",
                )
            ),
        ):
            with self.assertRaises(HTTPException) as context:
                await service.action_activate(
                    tenant_id=self.tenant_id,
                    entity_id=current.id,
                    where={"id": current.id},
                    auth_user_id=uuid.uuid4(),
                    data=RowVersionValidation(row_version=1),
                )
            self.assertEqual(context.exception.code, 409)
        with patch(
            "mugen.core.plugin.service_profile.service."
            "service_profile_subscription.load_commercial_contract",
            new=AsyncMock(return_value=SimpleNamespace(product_code="support.pro")),
        ):
            service._assert_allocation_available = AsyncMock(
                side_effect=SQLAlchemyError("db")
            )
            with self.assertRaises(HTTPException) as context:
                await service.action_activate(
                    tenant_id=self.tenant_id,
                    entity_id=current.id,
                    where={"id": current.id},
                    auth_user_id=uuid.uuid4(),
                    data=RowVersionValidation(row_version=1),
                )
            self.assertEqual(context.exception.code, 500)
        with self.assertRaises(HTTPException):
            await service.action_disable(
                tenant_id=self.tenant_id,
                entity_id=current.id,
                where={"id": current.id},
                auth_user_id=uuid.uuid4(),
                data=RowVersionValidation(row_version=1),
            )


class TestServiceProfileRuntime(unittest.IsolatedAsyncioTestCase):
    """Exercise fail-closed ingress and entitlement resolution."""

    async def test_ingress_resolution_success_and_failure_reasons(self) -> None:
        tenant_id = uuid.uuid4()
        binding_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        rsg = Mock()
        logger = Mock()
        service = DefaultServiceProfileResolver(rsg=rsg, logging_gateway=logger)

        scenarios = (
            ([], [], ServiceProfileResolutionReason.MISSING_ASSIGNMENT),
            (
                [{"id": uuid.uuid4()}, {"id": uuid.uuid4()}],
                [],
                ServiceProfileResolutionReason.AMBIGUOUS_ASSIGNMENT,
            ),
            (
                [{"service_profile_id": profile_id}],
                [None],
                ServiceProfileResolutionReason.INACTIVE_BINDING,
            ),
            (
                [{"service_profile_id": profile_id}],
                [{"id": binding_id}, None],
                ServiceProfileResolutionReason.INACTIVE_PROFILE,
            ),
        )
        for assignments, get_results, reason in scenarios:
            with self.subTest(reason=reason):
                rsg.find_many = AsyncMock(return_value=assignments)
                rsg.get_one = AsyncMock(side_effect=get_results)
                result = await service.resolve(
                    tenant_id=tenant_id,
                    ingress_binding_id=binding_id,
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.reason_code, reason.value)

        rsg.find_many = AsyncMock(return_value=[{"service_profile_id": profile_id}])
        rsg.get_one = AsyncMock(
            side_effect=[
                {"id": binding_id},
                {"id": profile_id, "key": "main", "display_name": "Main"},
            ]
        )
        result = await service.resolve(
            tenant_id=tenant_id,
            ingress_binding_id=binding_id,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.result.service_profile_id, profile_id)

        rsg.find_many = AsyncMock(side_effect=RuntimeError("db"))
        result = await service.resolve(
            tenant_id=tenant_id,
            ingress_binding_id=binding_id,
        )
        self.assertEqual(result.reason_code, "resolution_error")
        logger.error.assert_called_once()

    async def test_entitlement_exact_subscription_and_catalog_drift(self) -> None:
        now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        subscription_id = uuid.uuid4()
        account_id = uuid.uuid4()
        price_id = uuid.uuid4()
        product_id = uuid.uuid4()
        assignment = {
            "id": assignment_id,
            "billing_subscription_id": subscription_id,
            "product_code": "support.pro",
        }
        contract = SimpleNamespace(
            account={"id": account_id},
            subscription={"id": subscription_id, "status": "active"},
            price={"id": price_id},
            product={"id": product_id},
            product_code="support.pro",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=1),
        )
        rsg = Mock()
        rsg.get_one = AsyncMock(return_value={"id": profile_id})
        rsg.find_many = AsyncMock(return_value=[assignment])
        service = DefaultServiceProfileEntitlementService(
            rsg=rsg,
            logging_gateway=Mock(),
            clock=lambda: now,
        )
        with patch(
            "mugen.core.plugin.service_profile.service.runtime."
            "load_commercial_contract",
            new=AsyncMock(return_value=contract),
        ):
            result = await service.resolve(
                tenant_id=tenant_id,
                service_profile_id=profile_id,
                product_code=" SUPPORT.PRO ",
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.result.billing_subscription_id, subscription_id)

        contract.product_code = "renamed.product"
        with patch(
            "mugen.core.plugin.service_profile.service.runtime."
            "load_commercial_contract",
            new=AsyncMock(return_value=contract),
        ):
            result = await service.resolve(
                tenant_id=tenant_id,
                service_profile_id=profile_id,
                product_code="support.pro",
            )
        self.assertEqual(result.reason_code, "catalog_drift")

        rsg.find_many = AsyncMock(side_effect=[[], [assignment]])
        with patch(
            "mugen.core.plugin.service_profile.service.runtime."
            "load_commercial_contract",
            new=AsyncMock(return_value=contract),
        ):
            result = await service.resolve(
                tenant_id=tenant_id,
                service_profile_id=profile_id,
                product_code="renamed.product",
            )
        self.assertEqual(result.reason_code, "catalog_drift")

    async def test_entitlement_failure_reasons(self) -> None:
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        rsg = Mock()
        logger = Mock()
        service = DefaultServiceProfileEntitlementService(
            rsg=rsg,
            logging_gateway=logger,
        )
        rsg.get_one = AsyncMock(return_value=None)
        result = await service.resolve(
            tenant_id=tenant_id,
            service_profile_id=profile_id,
            product_code="product",
        )
        self.assertEqual(result.reason_code, "inactive_profile")

        rsg.get_one = AsyncMock(return_value={"id": profile_id})
        rsg.find_many = AsyncMock(side_effect=[[], []])
        result = await service.resolve(
            tenant_id=tenant_id,
            service_profile_id=profile_id,
            product_code="product",
        )
        self.assertEqual(result.reason_code, "missing_assignment")

        rsg.find_many = AsyncMock(return_value=[{}, {}])
        result = await service.resolve(
            tenant_id=tenant_id,
            service_profile_id=profile_id,
            product_code="product",
        )
        self.assertEqual(result.reason_code, "ambiguous_assignment")

        rsg.get_one = AsyncMock(side_effect=RuntimeError("db"))
        result = await service.resolve(
            tenant_id=tenant_id,
            service_profile_id=profile_id,
            product_code="product",
        )
        self.assertEqual(result.reason_code, "resolution_error")
        logger.error.assert_called_once()

        assignment = {
            "id": uuid.uuid4(),
            "billing_subscription_id": uuid.uuid4(),
            "product_code": "product",
        }
        rsg.get_one = AsyncMock(return_value={"id": profile_id})
        rsg.find_many = AsyncMock(return_value=[assignment])
        with patch(
            "mugen.core.plugin.service_profile.service.runtime."
            "load_commercial_contract",
            new=AsyncMock(
                side_effect=CommercialValidationError(
                    ServiceProfileEntitlementReason.INACTIVE_SUBSCRIPTION,
                    "inactive",
                )
            ),
        ):
            result = await service.resolve(
                tenant_id=tenant_id,
                service_profile_id=profile_id,
                product_code="product",
            )
        self.assertEqual(result.reason_code, "inactive_subscription")

        rsg.find_many = AsyncMock(return_value=[{"missing": True}])
        self.assertFalse(
            await service._has_catalog_drift(
                tenant_id=tenant_id,
                service_profile_id=profile_id,
                requested_code="product",
            )
        )
        valid_assignment = {
            "billing_subscription_id": uuid.uuid4(),
            "product_code": "product",
        }
        valid_contract = SimpleNamespace(product_code="product")
        rsg.find_many = AsyncMock(return_value=[valid_assignment])
        with patch(
            "mugen.core.plugin.service_profile.service.runtime."
            "load_commercial_contract",
            new=AsyncMock(return_value=valid_contract),
        ):
            self.assertFalse(
                await service._has_catalog_drift(
                    tenant_id=tenant_id,
                    service_profile_id=profile_id,
                    requested_code="product",
                )
            )


class TestServiceProfileExtension(unittest.IsolatedAsyncioTestCase):
    """Validate critical startup dependencies and runtime DI registration."""

    async def test_setup_registers_runtime_services(self) -> None:
        class _SqlGateway:
            pass

        gateway = _SqlGateway()
        registry = Mock()
        registry.get_resource.side_effect = lambda entity_set: SimpleNamespace(
            service_key=entity_set
        )
        registry.get_edm_service.side_effect = lambda service_key: service_key
        container = SimpleNamespace(
            get_required_ext_service=Mock(return_value=registry),
            register_ext_services=Mock(),
        )
        with (
            patch.object(
                fw_ext_module, "SQLAlchemyRelationalStorageGateway", _SqlGateway
            ),
            patch.object(fw_ext_module.di, "container", container),
        ):
            extension = ServiceProfileFWExtension(
                rsg_provider=lambda: gateway,
                logging_provider=Mock,
            )
            self.assertEqual(extension.platforms, [])
            await extension.setup(Mock())
        services = container.register_ext_services.call_args.args[0]
        self.assertIn(fw_ext_module.di.EXT_SERVICE_SERVICE_PROFILE_RESOLVER, services)
        self.assertIn(
            fw_ext_module.di.EXT_SERVICE_SERVICE_PROFILE_ENTITLEMENT, services
        )

    def test_default_providers_read_the_core_container(self) -> None:
        container = SimpleNamespace(
            relational_storage_gateway="rsg",
            logging_gateway="logger",
        )
        with patch.object(fw_ext_module.di, "container", container):
            self.assertEqual(fw_ext_module._rsg_provider(), "rsg")
            self.assertEqual(fw_ext_module._logging_provider(), "logger")

    async def test_dependency_failures_are_specific(self) -> None:
        extension = ServiceProfileFWExtension(
            rsg_provider=Mock,
            logging_provider=Mock,
        )
        with self.assertRaisesRegex(RuntimeError, "SQLAlchemy"):
            await extension.setup(Mock())

        class _SqlGateway:
            pass

        gateway = _SqlGateway()
        missing_container = SimpleNamespace(
            get_required_ext_service=Mock(side_effect=KeyError("registry"))
        )
        with (
            patch.object(
                fw_ext_module, "SQLAlchemyRelationalStorageGateway", _SqlGateway
            ),
            patch.object(fw_ext_module.di, "container", missing_container),
        ):
            extension = ServiceProfileFWExtension(
                rsg_provider=lambda: gateway,
                logging_provider=Mock,
            )
            with self.assertRaisesRegex(RuntimeError, "ACP framework"):
                await extension.setup(Mock())

        registry = Mock()
        registry.get_resource.side_effect = KeyError("missing")
        registry.get_edm_service = Mock()
        container = SimpleNamespace(
            get_required_ext_service=Mock(return_value=registry)
        )
        with (
            patch.object(
                fw_ext_module, "SQLAlchemyRelationalStorageGateway", _SqlGateway
            ),
            patch.object(fw_ext_module.di, "container", container),
        ):
            extension = ServiceProfileFWExtension(
                rsg_provider=lambda: gateway,
                logging_provider=Mock,
            )
            with self.assertRaisesRegex(RuntimeError, "KnowledgeScopes"):
                await extension.setup(Mock())


if __name__ == "__main__":
    unittest.main()
