"""Tests for authorization of resource references across RGQL query options."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"
    for name, location in (("mugen", root), ("mugen.core", root / "core")):
        if name not in sys.modules:
            package = ModuleType(name)
            package.__path__ = [str(location)]
            sys.modules[name] = package
    setattr(sys.modules["mugen"], "core", sys.modules["mugen.core"])


_bootstrap_namespace_packages()

# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.utility.rgql.query_authorization import authorize_query_paths
from mugen.core.utility.rgql.ast import (
    BinaryOp,
    CastExpr,
    FunctionCall,
    Identifier,
    IsOfExpr,
    LambdaCall,
    Literal,
    MemberAccess,
    TypeRef as AstTypeRef,
    UnaryOp,
)
from mugen.core.utility.rgql.model import (
    EdmModel,
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)
from mugen.core.utility.rgql.url_parser import RGQLQueryOptions, parse_rgql_url


class TestQueryPathAuthorization(unittest.IsolatedAsyncioTestCase):
    """Check every path source and expression scope without storage services."""

    def setUp(self) -> None:
        self.model = EdmModel()
        self.base = EdmType(
            name="Test.Record",
            kind="entity",
            properties={
                "Title": EdmProperty("Title", TypeRef("Edm.String")),
                "Detail": EdmProperty("Detail", TypeRef("Test.Detail")),
            },
            nav_properties={
                "Owner": EdmNavigationProperty("Owner", TypeRef("Test.Person")),
                "People": EdmNavigationProperty(
                    "People", TypeRef("Test.Person", is_collection=True)
                ),
            },
        )
        self.person = EdmType(
            name="Test.Person",
            kind="entity",
            properties={"Name": EdmProperty("Name", TypeRef("Edm.String"))},
            nav_properties={
                "Group": EdmNavigationProperty("Group", TypeRef("Test.Group")),
                "Manager": EdmNavigationProperty("Manager", TypeRef("Test.Person")),
                "Reports": EdmNavigationProperty(
                    "Reports", TypeRef("Test.Person", is_collection=True)
                ),
            },
        )
        group = EdmType(
            name="Test.Group",
            kind="entity",
            properties={"Name": EdmProperty("Name", TypeRef("Edm.String"))},
        )
        detail = EdmType(
            name="Test.Detail",
            kind="complex",
            nav_properties={
                "Contact": EdmNavigationProperty("Contact", TypeRef("Test.Person"))
            },
        )
        for edm_type in (self.base, self.person, group, detail):
            self.model.add_type(edm_type)
        self.permission = AsyncMock(return_value=True)

    async def _authorize(self, options, **kwargs) -> None:
        await authorize_query_paths(
            options=options,
            edm_type=self.base,
            model=self.model,
            path_permission_provider=self.permission,
            **kwargs,
        )

    def _calls(self) -> list[tuple[str, str]]:
        return [
            (call.args[0].name, call.args[1])
            for call in self.permission.await_args_list
        ]

    async def test_denied_relationship_across_query_options_and_operators(self) -> None:
        expressions = [
            f"$filter=Owner/Name {operator} 'a'"
            for operator in ("eq", "ne", "gt", "ge", "lt", "le")
        ]
        expressions.extend(
            [
                "$filter=Owner/Name in [%22a%22,%22b%22]",
                "$filter=contains(Owner/Name,'a')",
                "$filter=startswith(Owner/Name,'a')",
                "$filter=endswith(Owner/Name,'a')",
                "$filter=not (Owner/Name eq 'a')",
                "$filter=Title eq 'a' and Owner/Name eq 'b'",
                "$filter=Title eq 'a' or Owner/Name eq 'b'",
                "$filter=Title eq Owner/Name",
                "$filter=contains(Title,Owner/Name)",
                "$orderby=Owner/Name desc",
                "$select=Owner/Name",
                "$compute=length(Owner/Name) as Size",
                "$apply=aggregate(Owner/Name with countdistinct as Total)",
                "$apply=groupby((Owner/Name))",
                "$apply=groupby((Title),aggregate(Owner/Name with max as Last))",
                "$apply=filter(Owner/Name eq 'a')",
                "$apply=orderby(Owner/Name)",
                "$apply=compute(length(Owner/Name) as Size)",
                "$apply=topcount(1,Owner/Name)",
                "$apply=topcount(length(Owner/Name),Title)",
                "$apply=concat(identity(),filter(Owner/Name eq 'a'))",
                "@name=Owner/Name",
                "$search=alice",
                "$apply=search(alice)",
            ]
        )
        self.permission.return_value = False
        for query in expressions:
            with self.subTest(query=query):
                self.permission.reset_mock()
                options = parse_rgql_url(f"/Records?{query}").query
                with self.assertRaises(PermissionError):
                    await self._authorize(options, search_fields=("Owner/Name",))
                self.assertEqual(self._calls(), [("Test.Record", "Owner")])

    async def test_checks_intermediate_and_final_navigation_hops(self) -> None:
        options = parse_rgql_url("/Records?$filter=Owner/Group/Name eq 'a'").query
        self.permission.side_effect = lambda base, _path: base is self.base
        with self.assertRaises(PermissionError):
            await self._authorize(options)
        self.assertEqual(
            self._calls(), [("Test.Record", "Owner"), ("Test.Person", "Group")]
        )

    async def test_resolves_complex_paths_and_alias_member_types(self) -> None:
        options = RGQLQueryOptions(
            param_aliases={"@owner": Identifier("Owner")},
            filter=MemberAccess(Identifier("@owner"), "Manager"),
            select=["Detail/Contact/Group/Name"],
        )
        await self._authorize(options)
        self.assertEqual(
            self._calls(),
            [
                ("Test.Record", "Owner"),
                ("Test.Person", "Manager"),
                ("Test.Detail", "Contact"),
                ("Test.Person", "Group"),
            ],
        )

    async def test_lambda_scope_checks_sources_and_nested_variable_references(
        self,
    ) -> None:
        options = parse_rgql_url(
            "/Records?$filter=People/any(p:p/Group/Name eq 'a')"
        ).query
        await self._authorize(options)
        self.assertEqual(
            self._calls(), [("Test.Record", "People"), ("Test.Person", "Group")]
        )
        self.permission.reset_mock()
        options.filter = LambdaCall(
            "all", Identifier("People"), None, MemberAccess(Identifier("Group"), "Name")
        )
        await self._authorize(options)
        self.assertEqual(
            self._calls(), [("Test.Record", "People"), ("Test.Person", "Group")]
        )
        self.permission.reset_mock()
        options.filter = LambdaCall("any", Identifier("People"), None, None)
        self.permission.return_value = False
        with self.assertRaises(PermissionError):
            await self._authorize(options)
        self.assertEqual(self._calls(), [("Test.Record", "People")])

    async def test_casts_and_structured_function_results_preserve_navigation_types(
        self,
    ) -> None:
        person_ref = AstTypeRef(False, "Test", "Person", "Test.Person")
        expressions = (
            MemberAccess(CastExpr(Identifier("Owner"), person_ref), "Group"),
            MemberAccess(FunctionCall("custom", [Identifier("Owner")]), "Group"),
            MemberAccess(UnaryOp("neg", Identifier("Owner")), "Group"),
            MemberAccess(BinaryOp("add", Identifier("Owner"), Literal(1)), "Group"),
        )
        for expression in expressions:
            with self.subTest(expression=expression):
                self.permission.reset_mock()
                await self._authorize(RGQLQueryOptions(filter=expression))
                self.assertEqual(
                    self._calls(), [("Test.Record", "Owner"), ("Test.Person", "Group")]
                )

        self.permission.reset_mock()
        await self._authorize(
            RGQLQueryOptions(filter=IsOfExpr(Identifier("Owner"), person_ref))
        )
        self.assertEqual(self._calls(), [("Test.Record", "Owner")])
        self.permission.reset_mock()
        await self._authorize(
            RGQLQueryOptions(filter=MemberAccess(CastExpr(None, person_ref), "Group"))
        )
        self.assertEqual(self._calls(), [("Test.Person", "Group")])

    async def test_nested_lambda_variable_scopes(self) -> None:
        options = parse_rgql_url(
            "/Records?$filter=People/any(p:p/Reports/any(q:"
            "p/Group/Name eq q/Manager/Name))"
        ).query
        await self._authorize(options)
        self.assertEqual(
            self._calls(),
            [
                ("Test.Record", "People"),
                ("Test.Person", "Reports"),
                ("Test.Person", "Group"),
                ("Test.Person", "Manager"),
            ],
        )

    async def test_scalar_functions_inspect_all_arguments_and_return_scalar_types(
        self,
    ) -> None:
        await self._authorize(
            RGQLQueryOptions(
                filter=MemberAccess(
                    FunctionCall("concat", [Identifier("Owner"), Identifier("People")]),
                    "Group",
                )
            )
        )
        self.assertEqual(
            self._calls(), [("Test.Record", "Owner"), ("Test.Record", "People")]
        )
        self.permission.reset_mock()
        await self._authorize(RGQLQueryOptions(filter=FunctionCall("custom", [])))
        self.permission.assert_not_awaited()

    async def test_literals_unknown_paths_and_inactive_search_do_not_authorize(
        self,
    ) -> None:
        options = SimpleNamespace(
            filter=Literal({"path": Identifier("Owner")}),
            select=("Unknown/Name", "Title/Name", "*"),
            expand=[SimpleNamespace(path="Owner")],
            param_aliases={"@literal": Literal("Owner/Name")},
            orderby=[SimpleNamespace(expr=Identifier("@literal"))],
        )
        await self._authorize(options, search_fields=("Owner/Name",))
        self.permission.assert_not_awaited()
        self.base.properties["MockProperty"] = SimpleNamespace()
        await self._authorize(SimpleNamespace(select=["MockProperty"]))
        self.permission.assert_not_awaited()

    async def test_apply_count_noops_and_custom_raw_arguments_are_not_paths(
        self,
    ) -> None:
        options = parse_rgql_url(
            "/Records?$apply=aggregate($count as Total)/skip(1)/top(2)/identity()"
            "/custom(Owner/Name)&$compute=Title as Label"
        ).query
        await self._authorize(options)
        self.permission.assert_not_awaited()

    async def test_allowed_search_and_missing_options(self) -> None:
        await self._authorize(SimpleNamespace())
        await self._authorize(
            parse_rgql_url("/Records?$search=alice").query,
            search_fields=("Title", "Owner/Group/Name"),
        )
        self.assertEqual(
            self._calls(), [("Test.Record", "Owner"), ("Test.Person", "Group")]
        )
        self.permission.reset_mock()
        await self._authorize(
            parse_rgql_url(
                "/Records?$apply=groupby((Title),aggregate($count as Total))"
                "/search(alice)"
            ).query,
            search_fields=("Owner/Name",),
        )
        self.assertEqual(self._calls(), [("Test.Record", "Owner")])

    async def test_search_paths_use_storage_planner_normalization(self) -> None:
        self.permission.return_value = False
        options = parse_rgql_url("/Records?$search=alice").query
        for search_field in (
            "Owner /Name",
            "/Owner/Name",
            " Owner // Name / ",
        ):
            with self.subTest(search_field=search_field):
                self.permission.reset_mock()
                with self.assertRaises(PermissionError):
                    await self._authorize(options, search_fields=(search_field,))
                self.assertEqual(self._calls(), [("Test.Record", "Owner")])

        self.permission.return_value = True
        self.permission.reset_mock()
        await self._authorize(options, search_fields=(" / Owner // Group / Name / ",))
        self.assertEqual(
            self._calls(), [("Test.Record", "Owner"), ("Test.Person", "Group")]
        )
