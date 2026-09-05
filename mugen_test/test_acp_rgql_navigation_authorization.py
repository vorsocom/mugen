"""Regression tests for authorization of RGQL navigation query expressions."""

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
from urllib.parse import urlencode
import uuid
from unittest.mock import AsyncMock, Mock, patch

from quart import Quart
from werkzeug.exceptions import Forbidden


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"
    for name, path in (("mugen", root), ("mugen.core", root / "core")):
        if name not in sys.modules:
            package = ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package
            if "." in name:
                parent, child = name.rsplit(".", 1)
                setattr(sys.modules[parent], child, package)

    if "mugen.core.di" not in sys.modules:
        di_module = ModuleType("mugen.core.di")
        di_module.container = SimpleNamespace()
        sys.modules["mugen.core.di"] = di_module
        setattr(sys.modules["mugen.core"], "di", di_module)


_bootstrap_namespace_packages()

# pylint: disable=wrong-import-position
from mugen.core.contract.gateway.storage.rdbms.types import (
    RelatedOrderBy,
    RelatedPathHop,
    ScalarFilterOp,
    TextFilterOp,
)
from mugen.core.plugin.acp.api.decorator import rgql as rgql_mod
from mugen.core.utility.rgql.model import (
    EdmModel,
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    EntitySet,
    TypeRef,
)


_SEARCH_PATH_VARIANTS = {
    "Person/FirstName": (
        "/Person/FirstName",
        "Person /FirstName",
        "Person//FirstName",
        "\tPerson\t/ FirstName /",
    ),
    "Person/Company/Name": (
        " Person / Company /Name",
        "/Person//Company / Name/",
    ),
}


@dataclass
class _Record:
    id: uuid.UUID
    name: str
    person_id: uuid.UUID
    person: dict | None = None


@dataclass
class _Person:
    id: uuid.UUID
    first_name: str
    company_id: uuid.UUID


class _Registry:
    """Provide real EDM paths with separately permissioned mock services."""

    def __init__(self, search_fields: tuple[str, ...] = ()) -> None:
        definitions = (
            ("Record", "Records", {"Name": "Edm.String", "PersonId": "Edm.Guid"}),
            (
                "Person",
                "People",
                {"FirstName": "Edm.String", "CompanyId": "Edm.Guid"},
            ),
            ("Company", "Companies", {"Name": "Edm.String", "Revenue": "Edm.Int64"}),
        )
        types = {}
        entity_sets = {}
        self.resources = {}
        self.services = {}
        for name, entity_set, properties in definitions:
            type_name = f"SEC.{name}"
            types[type_name] = EdmType(
                name=type_name,
                kind="entity",
                key_properties=("Id",),
                entity_set_name=entity_set,
                properties={
                    key: EdmProperty(key, TypeRef(value))
                    for key, value in {"Id": "Edm.Guid", **properties}.items()
                },
            )
            entity_sets[entity_set] = EntitySet(entity_set, TypeRef(type_name))
            self.resources[entity_set] = SimpleNamespace(
                service_key=name,
                namespace=f"com.test.{name.lower()}",
                edm_type_name=type_name,
                permissions=SimpleNamespace(
                    permission_object=f"com.test.protected:{name.lower()}",
                    read=f"com.test.{name.lower()}:read",
                ),
                behavior=SimpleNamespace(
                    rgql_enabled=True,
                    rgql_max_expand_depth=None,
                    soft_delete=None,
                    search_fields=search_fields if name == "Record" else (),
                ),
            )
            self.services[name] = SimpleNamespace(
                table=f"admin_{name.lower()}",
                list=AsyncMock(return_value=[]),
                get=AsyncMock(return_value=None),
                count=AsyncMock(return_value=0),
            )

        types["SEC.Record"].nav_properties["Person"] = EdmNavigationProperty(
            "Person",
            TypeRef("SEC.Person"),
            source_fk="PersonId",
        )
        types["SEC.Person"].nav_properties["Company"] = EdmNavigationProperty(
            "Company",
            TypeRef("SEC.Company"),
            source_fk="CompanyId",
        )
        self.schema = EdmModel(types=types, entity_sets=entity_sets)
        self.schema_index = {
            name: resource.edm_type_name for name, resource in self.resources.items()
        }

    def get_resource(self, entity_set: str) -> SimpleNamespace:
        return self.resources[entity_set]

    def get_resource_by_type(self, type_name: str) -> SimpleNamespace:
        return next(
            resource
            for resource in self.resources.values()
            if resource.edm_type_name == type_name
        )

    def get_edm_service(self, service_key: str) -> SimpleNamespace:
        return self.services[service_key]


class TestAcpRgqlNavigationAuthorization(unittest.IsolatedAsyncioTestCase):
    """Deny navigation inference before query planning or any resource read."""

    async def asyncSetUp(self) -> None:
        self.app = Quart("test-acp-rgql-navigation-authorization")
        self.user_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()

    async def _request(
        self,
        options: dict[str, str],
        *,
        denied: tuple[str, ...] = (),
        search_fields: tuple[str, ...] = (),
        tenant_scoped: bool = False,
        expand_rows: bool = False,
        expect_denied: bool = False,
    ) -> SimpleNamespace:
        registry = _Registry(search_fields)
        record = _Record(uuid.uuid4(), "Visible", uuid.uuid4())
        registry.services["Record"].list.return_value = [record]
        registry.services["Record"].count.return_value = 1
        if expand_rows:
            registry.services["Person"].list.return_value = [
                _Person(record.person_id, "Alice", uuid.uuid4())
            ]

        async def _has_permission(**kwargs) -> bool:
            return kwargs["permission_object"] not in {
                f"com.test.protected:{name.lower()}" for name in denied
            }

        auth = SimpleNamespace(has_permission=AsyncMock(side_effect=_has_permission))
        endpoint = AsyncMock(side_effect=lambda **kwargs: kwargs)
        wrapped = rgql_mod.rgql_enabled(
            tenant_kw="tenant_id" if tenant_scoped else None,
            config_provider=lambda: SimpleNamespace(acp=SimpleNamespace()),
            logger_provider=lambda: SimpleNamespace(debug=Mock(), error=Mock()),
            auth_provider=lambda: auth,
            registry_provider=lambda: registry,
        )(endpoint)
        kwargs = {"entity_set": "Records", "auth_user": str(self.user_id)}
        if tenant_scoped:
            kwargs["tenant_id"] = str(self.tenant_id)
        build_query = rgql_mod.RGQLToRelationalAdapter.build_relational_query
        with patch.object(
            rgql_mod.RGQLToRelationalAdapter,
            "build_relational_query",
            autospec=True,
            side_effect=build_query,
        ) as build:
            async with self.app.test_request_context(
                f"/api/core/acp/v1/Records?{urlencode(options)}",
                method="GET",
            ):
                if expect_denied:
                    with self.assertRaises(Forbidden):
                        await wrapped(**kwargs)
                    result = None
                else:
                    result = await wrapped(**kwargs)

        if expect_denied:
            build.assert_not_called()
            endpoint.assert_not_awaited()
            for service in registry.services.values():
                service.list.assert_not_awaited()
                service.get.assert_not_awaited()
                service.count.assert_not_awaited()
            denied_objects = {
                f"com.test.protected:{name.lower()}" for name in denied
            }
            self.assertTrue(
                any(
                    call.kwargs["permission_object"] in denied_objects
                    for call in auth.has_permission.await_args_list
                ),
                "The forbidden relationship must actually be authorized.",
            )

        return SimpleNamespace(
            registry=registry,
            auth=auth,
            build=build,
            result=result,
        )

    async def test_scalar_operators_require_target_read(self) -> None:
        for operator in ("eq", "ne", "gt", "ge", "lt", "le", "in"):
            with self.subTest(operator=operator):
                value = "('Alice','Bob')" if operator == "in" else "'Alice'"
                await self._request(
                    {"$filter": f"Person/FirstName {operator} {value}"},
                    denied=("Person",),
                    expect_denied=True,
                )

    async def test_text_operators_require_target_read(self) -> None:
        for function in ("contains", "startswith", "endswith"):
            with self.subTest(function=function):
                await self._request(
                    {"$filter": f"{function}(Person/FirstName,'Alice')"},
                    denied=("Person",),
                    expect_denied=True,
                )

    async def test_boolean_branches_cannot_skip_authorization(self) -> None:
        expressions = (
            "Name eq 'Visible' and Person/FirstName eq 'Alice'",
            "Name eq 'Visible' or Person/FirstName eq 'Alice'",
            "Person/FirstName eq 'Alice' or Name eq 'Visible'",
            "true or Person/FirstName eq 'Alice'",
            "false and Person/FirstName eq 'Alice'",
            "not (Person/FirstName eq 'Alice')",
        )
        for expression in expressions:
            with self.subTest(expression=expression):
                await self._request(
                    {"$filter": expression},
                    denied=("Person",),
                    expect_denied=True,
                )

    async def test_ordering_requires_target_read(self) -> None:
        for direction in ("asc", "desc"):
            with self.subTest(direction=direction):
                await self._request(
                    {"$orderby": f"Person/FirstName {direction}"},
                    denied=("Person",),
                    expect_denied=True,
                )

    async def test_filtered_count_requires_target_read(self) -> None:
        await self._request(
            {"$filter": "Person/FirstName eq 'Alice'", "$count": "true"},
            denied=("Person",),
            expect_denied=True,
        )

    async def test_configured_navigation_search_requires_target_read(self) -> None:
        for search in ("Alice", "Alice OR Visible", "Alice AND Visible"):
            with self.subTest(search=search):
                await self._request(
                    {"$search": search},
                    search_fields=("Name", "Person/FirstName"),
                    denied=("Person",),
                    expect_denied=True,
                )

    async def test_search_path_normalization_cannot_bypass_authorization(self) -> None:
        for canonical, variants in _SEARCH_PATH_VARIANTS.items():
            denied_types = (
                ("Person", "Company") if "Company" in canonical else ("Person",)
            )
            for field in variants:
                for denied_type in denied_types:
                    with self.subTest(field=field, denied=denied_type):
                        await self._request(
                            {"$search": "Alice"},
                            search_fields=(field,),
                            denied=(denied_type,),
                            expect_denied=True,
                        )

    async def test_multihop_requires_intermediate_and_terminal_read(self) -> None:
        options = (
            {"$filter": "Person/Company/Name eq 'Protected'"},
            {"$orderby": "Person/Company/Name desc"},
            {"$search": "Protected"},
        )
        for denied_type in ("Person", "Company"):
            for query in options:
                with self.subTest(denied=denied_type, query=query):
                    await self._request(
                        query,
                        search_fields=("Person/Company/Name",),
                        denied=(denied_type,),
                        expect_denied=True,
                    )

    async def test_nested_expansion_expressions_preflight_before_read(self) -> None:
        expressions = (
            "$filter=Company/Name eq 'Protected'",
            "$orderby=Company/Name desc",
            "$filter=contains(Company/Name,'Protected');$count=true",
        )
        for expression in expressions:
            with self.subTest(expression=expression):
                await self._request(
                    {"$expand": f"Person({expression})"},
                    denied=("Company",),
                    expect_denied=True,
                )

    async def test_compute_and_apply_references_require_target_read(self) -> None:
        options = (
            {"$compute": "Person/FirstName as RelatedName"},
            {"$apply": "filter(Person/FirstName eq 'Alice')"},
            {"$apply": "orderby(Person/FirstName desc)"},
            {"$apply": "compute(Person/FirstName as RelatedName)"},
            {"$apply": "aggregate(Person/Company/Revenue with sum as Total)"},
            {"$apply": "groupby((Person/FirstName),aggregate($count as Total))"},
            {"$apply": "topcount(1,Person/Company/Revenue)"},
            {"$apply": "concat(identity(),filter(Person/FirstName eq 'Alice'))"},
        )
        for query in options:
            with self.subTest(query=query):
                await self._request(
                    query,
                    denied=("Person",),
                    expect_denied=True,
                )

    async def test_target_permission_uses_request_identity_and_tenant(self) -> None:
        outcome = await self._request(
            {"$filter": "Person/FirstName eq 'Alice'"},
            denied=("Person",),
            tenant_scoped=True,
            expect_denied=True,
        )
        outcome.auth.has_permission.assert_any_await(
            user_id=self.user_id,
            permission_object="com.test.protected:person",
            permission_type="com.test.person:read",
            tenant_id=self.tenant_id,
            allow_global_admin=False,
        )

    async def test_permitted_navigation_retains_filter_order_count_plan(self) -> None:
        outcome = await self._request(
            {
                "$filter": "Person/FirstName eq 'Alice'",
                "$orderby": "Person/Company/Revenue desc",
                "$count": "true",
            }
        )
        service = outcome.registry.services["Record"]
        outcome.build.assert_called_once()
        service.list.assert_awaited_once()
        service.count.assert_awaited_once()
        query = service.list.await_args.kwargs
        first_hop = RelatedPathHop("admin_record", "person_id", "admin_person", "id")
        predicate = query["filter_groups"][0].related_scalar_filters[0]
        self.assertEqual(predicate.path_hops, [first_hop])
        self.assertEqual(predicate.field, "first_name")
        self.assertIs(predicate.op, ScalarFilterOp.EQ)
        self.assertEqual(predicate.value, "Alice")
        self.assertEqual(
            query["order_by"],
            [
                RelatedOrderBy(
                    path_hops=[
                        first_hop,
                        RelatedPathHop(
                            "admin_person", "company_id", "admin_company", "id"
                        ),
                    ],
                    field="revenue",
                    descending=True,
                )
            ],
        )
        self.assertEqual(
            service.count.await_args.kwargs["filter_groups"],
            query["filter_groups"],
        )
        self.assertEqual(outcome.result["rgql"].count, 1)
        self.assertEqual(outcome.result["rgql"].values[0]["Name"], "Visible")
        authorized = {
            call.kwargs["permission_object"]
            for call in outcome.auth.has_permission.await_args_list
        }
        self.assertTrue(
            {"com.test.protected:person", "com.test.protected:company"} <= authorized
        )

    async def test_permitted_navigation_search_retains_related_text_plan(self) -> None:
        outcome = await self._request(
            {"$search": "Alice"},
            search_fields=("Name", "Person/FirstName"),
        )
        groups = outcome.registry.services["Record"].list.await_args.kwargs[
            "filter_groups"
        ]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].text_filters[0].field, "name")
        predicate = groups[1].related_text_filters[0]
        self.assertEqual(predicate.path_hops[0].target_table, "admin_person")
        self.assertEqual(predicate.field, "first_name")
        self.assertIs(predicate.op, TextFilterOp.CONTAINS)
        self.assertEqual(predicate.value, "Alice")
        self.assertFalse(predicate.case_sensitive)

    async def test_permitted_search_path_variants_preserve_related_plan(self) -> None:
        for canonical, variants in _SEARCH_PATH_VARIANTS.items():
            baseline = await self._request(
                {"$search": "Alice"},
                search_fields=(canonical,),
            )
            expected = baseline.registry.services["Record"].list.await_args.kwargs[
                "filter_groups"
            ]
            for field in variants:
                with self.subTest(field=field):
                    outcome = await self._request(
                        {"$search": "Alice"},
                        search_fields=(field,),
                    )
                    actual = outcome.registry.services["Record"].list.await_args.kwargs[
                        "filter_groups"
                    ]
                    self.assertEqual(actual, expected)
                    self.assertEqual(
                        outcome.auth.has_permission.await_args_list,
                        baseline.auth.has_permission.await_args_list,
                    )

    async def test_plain_base_query_does_not_require_unrelated_read(self) -> None:
        outcome = await self._request(
            {"$filter": "Name eq 'Visible'", "$orderby": "Name asc"},
            denied=("Person", "Company"),
            search_fields=("Person/FirstName",),
        )
        self.assertEqual(outcome.result["rgql"].values[0]["Name"], "Visible")
        outcome.auth.has_permission.assert_not_awaited()
        outcome.registry.services["Record"].list.assert_awaited_once()

    async def test_explicit_denied_expansion_is_suppressed(self) -> None:
        outcome = await self._request(
            {"$expand": "Person"},
            denied=("Person",),
            expand_rows=True,
        )
        self.assertNotIn("Person", outcome.result["rgql"].values[0])
        outcome.registry.services["Record"].list.assert_awaited_once()
        outcome.registry.services["Person"].list.assert_not_awaited()
        outcome.auth.has_permission.assert_any_await(
            user_id=self.user_id,
            permission_object="com.test.protected:person",
            permission_type="com.test.person:read",
            tenant_id=None,
            allow_global_admin=False,
        )

    async def test_permitted_expansion_materializes_related_resource(self) -> None:
        outcome = await self._request({"$expand": "Person"}, expand_rows=True)
        self.assertEqual(
            outcome.result["rgql"].values[0]["Person"]["FirstName"], "Alice"
        )
        outcome.registry.services["Person"].list.assert_awaited_once()
