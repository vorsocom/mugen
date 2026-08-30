"""Tests for Billing entitlement bucket catalog reference expansions."""

from dataclasses import fields
from datetime import datetime, timezone
from typing import Any, Sequence
import unittest
import uuid

from sqlalchemy.orm import RelationshipProperty

from mugen.core.contract.gateway.storage.rdbms.types import ScalarFilterOp
from mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_expand import (
    ExpansionContext,
    expand_navs_bulk,
    expand_navs_recursive,
)
from mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_to_relational import (
    RGQLToRelationalAdapter,
)
from mugen.core.plugin.billing.domain import (
    EntitlementBucketDE,
    MeterDefinitionDE,
    PriceDE,
    PriceEntitlementDE,
    ProductDE,
)
from mugen.core.plugin.billing.edm import (
    entitlement_bucket_type,
    meter_definition_type,
    price_entitlement_type,
    price_type,
    product_type,
)
from mugen.core.plugin.billing.model import EntitlementBucket
from mugen.core.utility.rgql.model import EdmModel, EdmType
from mugen.core.utility.rgql.url_parser import ExpandItem
from mugen.core.utility.string.case_conversion_helper import (
    snake_to_title,
    title_to_snake,
)


class _MemoryService:
    """Minimal relational service used to exercise real expansion planning."""

    def __init__(self, rows: Sequence[Any]):
        self.rows = list(rows)
        self.last_get: dict[str, Any] | None = None
        self.last_list: dict[str, Any] | None = None

    @staticmethod
    def _matches(row: Any, filter_groups: Sequence[Any] | None) -> bool:
        if not filter_groups:
            return True
        for group in filter_groups:
            if any(
                getattr(row, field_name, None) != value
                for field_name, value in group.where.items()
            ):
                continue
            scalar_match = True
            for item in group.scalar_filters:
                actual = getattr(row, item.field, None)
                if item.op == ScalarFilterOp.IN:
                    scalar_match = actual in item.value
                elif item.op == ScalarFilterOp.EQ:
                    scalar_match = actual == item.value
                else:
                    raise AssertionError(f"Unexpected scalar operation: {item.op}")
                if not scalar_match:
                    break
            if scalar_match:
                return True
        return False

    async def get(
        self,
        where: dict[str, Any],
        columns: Sequence[str] | None = None,
    ) -> Any | None:
        self.last_get = {"where": where, "columns": columns}
        for row in self.rows:
            if all(getattr(row, key, None) == value for key, value in where.items()):
                return row
        return None

    async def list(self, **kwargs: Any) -> list[Any]:
        self.last_list = kwargs
        return [
            row
            for row in self.rows
            if self._matches(row, kwargs.get("filter_groups"))
        ]


def _serialize(
    entity: Any,
    edm_type: EdmType,
    columns: Sequence[str] | None,
    expand_paths: set[str],
) -> dict[str, Any]:
    """Mirror ACP field selection closely enough to verify nested materialization."""
    result: dict[str, Any] = {}
    for field in fields(entity):
        value = getattr(entity, field.name)
        title = snake_to_title(field.name)
        prop = edm_type.properties.get(title)
        always_serialize = bool(getattr(prop, "always_serialize", False))
        if value is None and not always_serialize:
            continue
        if (
            columns is None
            or field.name in columns
            or title in expand_paths
            or always_serialize
        ):
            result[title] = value
    return result


class TestBillingEntitlementBucketRelationshipContract(unittest.TestCase):
    """Covers ORM, domain, and EDM relationship-name consistency."""

    def test_catalog_reference_relationships_align_across_layers(self) -> None:
        domain_fields = {field.name for field in fields(EntitlementBucketDE)}
        mapper_properties = EntitlementBucket.__mapper__._props
        expected = {
            "PriceEntitlement": (
                "price_entitlement",
                "PriceEntitlementId",
                "BILLING.PriceEntitlement",
            ),
            "MeterDefinition": (
                "meter_definition",
                "MeterDefinitionId",
                "BILLING.MeterDefinition",
            ),
        }

        for nav_name, (relationship_name, source_fk, target_type) in expected.items():
            with self.subTest(navigation=nav_name):
                navigation = entitlement_bucket_type.nav_properties[nav_name]
                self.assertEqual(title_to_snake(nav_name), relationship_name)
                self.assertEqual(navigation.source_fk, source_fk)
                self.assertEqual(navigation.target_type.name, target_type)
                self.assertIn(relationship_name, domain_fields)
                self.assertIsInstance(
                    mapper_properties[relationship_name],
                    RelationshipProperty,
                )


class TestBillingEntitlementBucketExpansionMaterialization(
    unittest.IsolatedAsyncioTestCase
):
    """Covers collection and entity catalog-reference materialization."""

    def setUp(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.product_id = uuid.uuid4()
        self.price_id = uuid.uuid4()
        self.entitlement_id = uuid.uuid4()
        self.meter_id = uuid.uuid4()
        self.bucket_id = uuid.uuid4()
        archived_at = datetime(2026, 8, 1, tzinfo=timezone.utc)

        self.product = ProductDE(
            id=self.product_id,
            code="valet-customer-inbox-lite",
            name="Valet Customer Inbox Lite",
        )
        self.price = PriceDE(
            id=self.price_id,
            product_id=self.product_id,
            code="valet-customer-inbox-lite-monthly-usd-v1",
            price_type="recurring",
            currency="USD",
            deleted_at=archived_at,
        )
        self.meter = MeterDefinitionDE(
            id=self.meter_id,
            code="valet.customer-inbox.minutes",
            description="Customer Inbox minutes",
            unit="minute",
            is_active=False,
        )
        self.entitlement = PriceEntitlementDE(
            id=self.entitlement_id,
            price_id=self.price_id,
            meter_definition_id=self.meter_id,
            included_quantity=150,
            rollover_policy="none",
            deleted_at=archived_at,
        )

        self.services = {
            "BILLING.Product": _MemoryService([self.product]),
            "BILLING.Price": _MemoryService([self.price]),
            "BILLING.PriceEntitlement": _MemoryService([self.entitlement]),
            "BILLING.MeterDefinition": _MemoryService([self.meter]),
        }
        model = EdmModel()
        for edm_type in (
            entitlement_bucket_type,
            price_entitlement_type,
            price_type,
            product_type,
            meter_definition_type,
        ):
            model.add_type(edm_type)

        async def _allow(_edm_type: EdmType, _path: str) -> bool:
            return True

        def _default_where(type_name: str) -> dict[str, Any]:
            if type_name in {
                "BILLING.PriceEntitlement",
                "BILLING.Price",
                "BILLING.Product",
            }:
                return {"deleted_at": None}
            return {}

        def _reference_where(type_name: str) -> dict[str, Any]:
            if type_name in {
                "BILLING.PriceEntitlement",
                "BILLING.Price",
                "BILLING.Product",
            }:
                return {}
            return _default_where(type_name)

        self.context = ExpansionContext(
            model=model,
            adapter=RGQLToRelationalAdapter(),
            serialization_provider=_serialize,
            service_resolver=lambda type_name: self.services[type_name],
            path_permission_provider=_allow,
            max_depth=5,
            allow_expand_wildcard=False,
            default_top=100,
            max_top=100,
            max_skip=100,
            max_select=100,
            max_orderby=100,
            max_expand_paths=100,
            max_filter_terms=100,
            default_where_provider=_default_where,
            forward_reference_where_provider=_reference_where,
        )
        self.price_entitlement_expand = ExpandItem(
            path="PriceEntitlement",
            select=["IncludedQuantity", "PriceId", "MeterDefinitionId"],
            expand=[
                ExpandItem(
                    path="Price",
                    select=["Code", "ProductId"],
                    expand=[ExpandItem(path="Product", select=["Name"])],
                ),
                ExpandItem(
                    path="MeterDefinition",
                    select=["Code", "Description", "Unit", "IsActive"],
                ),
            ],
        )
        self.meter_expand = ExpandItem(
            path="MeterDefinition",
            select=["Code", "Description", "Unit", "IsActive"],
        )

    def _bucket(self) -> EntitlementBucketDE:
        return EntitlementBucketDE(
            id=self.bucket_id,
            tenant_id=self.tenant_id,
            price_entitlement_id=self.entitlement_id,
            meter_definition_id=self.meter_id,
        )

    def _assert_expanded_labels(self, bucket: EntitlementBucketDE) -> None:
        self.assertEqual(bucket.price_entitlement["IncludedQuantity"], 150)
        self.assertEqual(
            bucket.price_entitlement["Price"]["Code"],
            "valet-customer-inbox-lite-monthly-usd-v1",
        )
        self.assertEqual(
            bucket.price_entitlement["Price"]["Product"]["Name"],
            "Valet Customer Inbox Lite",
        )
        self.assertEqual(
            bucket.price_entitlement["MeterDefinition"]["Code"],
            "valet.customer-inbox.minutes",
        )
        self.assertEqual(
            bucket.meter_definition["Description"],
            "Customer Inbox minutes",
        )

    async def test_collection_expands_nested_catalog_references(self) -> None:
        bucket = self._bucket()

        for expansion in (self.price_entitlement_expand, self.meter_expand):
            await expand_navs_bulk(
                root_entities=[bucket],
                ctx=self.context,
                expand_item=expansion,
                current_type_name=entitlement_bucket_type.name,
                depth=0,
                levels_remaining=5,
            )

        self._assert_expanded_labels(bucket)
        self.assertEqual(bucket.tenant_id, self.tenant_id)

    async def test_entity_expands_archived_entitlement_and_inactive_meter(self) -> None:
        bucket = self._bucket()

        for expansion in (self.price_entitlement_expand, self.meter_expand):
            await expand_navs_recursive(
                root_entity=bucket,
                ctx=self.context,
                expand_item=expansion,
                current_type_name=entitlement_bucket_type.name,
                depth=0,
                levels_remaining=5,
            )

        self._assert_expanded_labels(bucket)
        self.assertIsNotNone(bucket.price_entitlement["DeletedAt"])
        self.assertIsNotNone(bucket.price_entitlement["Price"]["DeletedAt"])
        self.assertFalse(bucket.meter_definition["IsActive"])
        self.assertFalse(
            bucket.price_entitlement["MeterDefinition"]["IsActive"]
        )

