"""Unit tests for opt-in ACP archived collection views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from quart import Quart

from mugen.core.contract.gateway.storage.rdbms.types import ScalarFilterOp
from mugen.core.plugin.acp.api.decorator import rgql as rgql_mod
from mugen.core.plugin.acp.contract.sdk.resource import (
    AdminBehavior,
    SoftDeleteMode,
    SoftDeletePolicy,
)
from mugen.core.plugin.billing.domain import PriceDE, ProductDE
from mugen.core.plugin.billing.edm.price import price_type
from mugen.core.plugin.billing.edm.product import product_type
from mugen.core.utility.rgql.model import (
    EdmModel,
    EdmProperty,
    EdmType,
    EntitySet,
    TypeRef,
)


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None) -> None:
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None) -> None:
    raise _AbortCalled(code, message)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        acp=SimpleNamespace(
            rgql_default_top=100,
            rgql_max_top=500,
            rgql_max_skip=10_000,
            rgql_max_select=50,
            rgql_max_orderby=5,
            rgql_max_expand_paths=10,
            rgql_allow_expand_wildcard=False,
            rgql_max_filter_terms=25,
            rgql_max_filter_nav_depth=4,
            rgql_max_expand_depth=3,
        )
    )


class _Registry:
    def __init__(
        self,
        *,
        entity_set: str,
        edm_type: EdmType,
        service: object,
        policy: SoftDeletePolicy,
    ) -> None:
        resource = SimpleNamespace(
            service_key="service",
            namespace="com.test.billing",
            edm_type_name=edm_type.name,
            behavior=AdminBehavior(soft_delete=policy),
        )
        self.schema_index = {entity_set: edm_type.name}
        self.schema = EdmModel(
            types={edm_type.name: edm_type},
            entity_sets={entity_set: EntitySet(entity_set, TypeRef(edm_type.name))},
        )
        self.resources = {entity_set: resource}
        self._resource = resource
        self._service = service
        self._edm_type = edm_type

    def get_resource(self, _entity_set: str) -> object:
        return self._resource

    def get_resource_by_type(self, edm_type_name: str) -> object:
        if edm_type_name != self._edm_type.name:
            raise KeyError(edm_type_name)
        return self._resource

    def get_edm_service(self, _service_key: str) -> object:
        return self._service


@dataclass
class _FlagEntity:
    id: uuid.UUID | None = None
    row_version: int | None = None
    is_deleted: bool | None = None


class TestMugenAcpArchivedCollectionViews(unittest.IsolatedAsyncioTestCase):
    """Covers archived view validation, filtering, and serialization."""

    async def asyncSetUp(self) -> None:
        self.app = Quart("archived-collection-views")
        self.auth_user = str(uuid.uuid4())
        self.auth_service = SimpleNamespace(
            has_permission=AsyncMock(return_value=True)
        )
        self.logger = SimpleNamespace(debug=Mock(), error=Mock())

    def _wrap(self, registry: _Registry):
        async def _endpoint(**kwargs):
            return kwargs

        return rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: self.logger,
            auth_provider=lambda: self.auth_service,
            registry_provider=lambda: registry,
        )(_endpoint)

    async def test_archived_view_composes_rgql_and_stable_projection(self) -> None:
        deleted_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
        product = ProductDE(
            id=uuid.uuid4(),
            code="archived",
            row_version=7,
            deleted_at=deleted_at,
        )
        service = SimpleNamespace(
            table="billing_product",
            list=AsyncMock(return_value=[product]),
            count=AsyncMock(return_value=1),
        )
        policy = SoftDeletePolicy(
            mode=SoftDeleteMode.TIMESTAMP,
            column="DeletedAt",
            allow_deleted_collection_views=True,
        )
        registry = _Registry(
            entity_set="BillingProducts",
            edm_type=product_type,
            service=service,
            policy=policy,
        )

        async with self.app.test_request_context(
            "/api/core/acp/v1/BillingProducts"
            "?$deleted=archived"
            "&$select=Code,DeletedAt,RowVersion,IsArchived"
            "&$filter=Code eq 'archived'"
            "&$orderby=Code desc"
            "&$top=1"
            "&$skip=2"
            "&$count=true",
            method="GET",
        ):
            result = await self._wrap(registry)(
                entity_set="BillingProducts",
                entity_id=None,
                auth_user=self.auth_user,
            )

        row = result["rgql"].values[0]
        self.assertEqual(row["Code"], "archived")
        self.assertEqual(row["DeletedAt"], deleted_at)
        self.assertEqual(row["RowVersion"], 7)
        self.assertTrue(row["IsArchived"])
        self.assertEqual(
            service.list.await_args.kwargs["columns"],
            ["code", "deleted_at", "row_version"],
        )
        self.assertEqual(service.list.await_args.kwargs["limit"], 1)
        self.assertEqual(service.list.await_args.kwargs["offset"], 2)
        self.assertTrue(service.list.await_args.kwargs["order_by"][0].descending)
        filter_group = service.list.await_args.kwargs["filter_groups"][0]
        self.assertTrue(
            any(
                scalar.field == "deleted_at"
                and scalar.op is ScalarFilterOp.NE
                and scalar.value is None
                for scalar in filter_group.scalar_filters
            )
        )
        service.count.assert_awaited_once_with(
            filter_groups=service.list.await_args.kwargs["filter_groups"]
        )

    async def test_all_view_and_price_product_filter(self) -> None:
        product_id = uuid.uuid4()
        price = PriceDE(
            id=uuid.uuid4(),
            product_id=product_id,
            code="active",
            row_version=3,
            deleted_at=None,
        )
        service = SimpleNamespace(
            table="billing_price",
            list=AsyncMock(return_value=[price]),
            count=AsyncMock(return_value=1),
        )
        registry = _Registry(
            entity_set="BillingPrices",
            edm_type=price_type,
            service=service,
            policy=SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_deleted_collection_views=True,
            ),
        )

        async with self.app.test_request_context(
            "/api/core/acp/v1/BillingPrices"
            f"?$deleted=all&$filter=ProductId eq guid'{product_id}'"
            "&$select=Code",
            method="GET",
        ):
            result = await self._wrap(registry)(
                entity_set="BillingPrices",
                entity_id=None,
                auth_user=self.auth_user,
            )

        row = result["rgql"].values[0]
        self.assertEqual(row["DeletedAt"], None)
        self.assertEqual(row["RowVersion"], 3)
        self.assertFalse(row["IsArchived"])
        filter_group = service.list.await_args.kwargs["filter_groups"][0]
        self.assertNotIn("deleted_at", filter_group.where)
        self.assertEqual(filter_group.where["product_id"], product_id)

    async def test_flag_archived_view_uses_deleted_value(self) -> None:
        flag_type = EdmType(
            name="TEST.FlagArchive",
            kind="entity",
            properties={
                "Id": EdmProperty("Id", TypeRef("Edm.Guid")),
                "IsDeleted": EdmProperty(
                    "IsDeleted",
                    TypeRef("Edm.Boolean"),
                    always_serialize=True,
                ),
                "IsArchived": EdmProperty(
                    "IsArchived",
                    TypeRef("Edm.Boolean"),
                    computed=True,
                    always_serialize=True,
                ),
            },
            key_properties=("Id",),
            entity_set_name="FlagArchives",
        )
        entity = _FlagEntity(id=uuid.uuid4(), is_deleted=True)
        service = SimpleNamespace(
            table="flag_archive",
            list=AsyncMock(return_value=[entity]),
            count=AsyncMock(return_value=1),
        )
        registry = _Registry(
            entity_set="FlagArchives",
            edm_type=flag_type,
            service=service,
            policy=SoftDeletePolicy(
                mode=SoftDeleteMode.FLAG,
                column="IsDeleted",
                deleted_value=True,
                allow_deleted_collection_views=True,
            ),
        )

        async with self.app.test_request_context(
            "/api/core/acp/v1/FlagArchives?$deleted=archived&$select=Id",
            method="GET",
        ):
            result = await self._wrap(registry)(
                entity_set="FlagArchives",
                entity_id=None,
                auth_user=self.auth_user,
            )

        self.assertEqual(
            service.list.await_args.kwargs["filter_groups"][0].where,
            {"is_deleted": True},
        )
        self.assertTrue(result["rgql"].values[0]["IsArchived"])

    async def test_deleted_query_validation(self) -> None:
        enabled = SimpleNamespace(
            behavior=AdminBehavior(
                soft_delete=SoftDeletePolicy(
                    mode=SoftDeleteMode.TIMESTAMP,
                    column="DeletedAt",
                    allow_deleted_collection_views=True,
                )
            )
        )
        disabled = SimpleNamespace(behavior=AdminBehavior())
        cases = (
            ("?$deleted=archived", enabled, "entity-id"),
            ("?$deleted=invalid", enabled, None),
            ("?$deleted=active&$deleted=all", enabled, None),
            ("?$deleted=all", disabled, None),
        )

        with patch.object(rgql_mod, "abort", side_effect=_abort_raiser):
            for query, resource, entity_id in cases:
                with self.subTest(query=query, entity_id=entity_id):
                    async with self.app.test_request_context(query, method="GET"):
                        with self.assertRaises(_AbortCalled) as raised:
                            rgql_mod._deleted_collection_view(resource, entity_id)
                    self.assertEqual(raised.exception.code, 400)
