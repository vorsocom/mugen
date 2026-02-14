"""Unit tests for RGQL semantic checker internals."""

import datetime
import decimal
import uuid
import unittest

from mugen.core.utility.rgql.apply_parser import (
    AggregateExpression,
    AggregateTransform,
    BottomTopTransform,
    ComputeExpression,
    ComputeTransform,
    ConcatTransform,
    CustomApplyTransform,
    FilterTransform,
    GroupByTransform,
    IdentityTransform,
    OrderByTransform,
    SearchTransform,
    SkipTransform,
    TopTransform,
)
from mugen.core.utility.rgql.ast import (
    BinaryOp,
    EnumLiteral,
    Identifier,
    Literal,
    MemberAccess,
    SpatialLiteral,
)
from mugen.core.utility.rgql.expr_parser import parse_rgql_expr
from mugen.core.utility.rgql.orderby_parser import parse_orderby
from mugen.core.utility.rgql.model import (
    EdmModel,
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    EntitySet,
    TypeRef,
)
from mugen.core.utility.rgql.semantic import SemanticChecker, SemanticError, ValueType
from mugen.core.utility.rgql.url_parser import (
    ExpandItem,
    KeyComponent,
    RGQLPathSegment,
    RGQLQueryOptions,
)


class _UnknownTransform:  # mimic ApplyNode shape for negative branch
    pass


class TestMugenRgqlSemantic(unittest.TestCase):
    """Covers high-signal semantic checker branches and coercion rules."""

    def setUp(self) -> None:
        model = EdmModel()

        model.add_type(EdmType(name="NS.Color", kind="enum", enum_members={"Red", "Blue"}))

        model.add_type(
            EdmType(
                name="NS.Address",
                kind="complex",
                properties={
                    "Street": EdmProperty(name="Street", type=TypeRef("Edm.String")),
                },
            )
        )

        customer = EdmType(
            name="NS.Customer",
            kind="entity",
            properties={
                "Id": EdmProperty(name="Id", type=TypeRef("Edm.Guid")),
                "Name": EdmProperty(name="Name", type=TypeRef("Edm.String")),
                "Age": EdmProperty(name="Age", type=TypeRef("Edm.Int32")),
                "Address": EdmProperty(name="Address", type=TypeRef("NS.Address")),
                "Tags": EdmProperty(name="Tags", type=TypeRef("Edm.String", is_collection=True)),
                "Color": EdmProperty(name="Color", type=TypeRef("NS.Color")),
                "FilterOnly": EdmProperty(
                    name="FilterOnly",
                    type=TypeRef("Edm.String"),
                    sortable=False,
                ),
                "SortOnly": EdmProperty(
                    name="SortOnly",
                    type=TypeRef("Edm.String"),
                    filterable=False,
                ),
                "OwnerId": EdmProperty(name="OwnerId", type=TypeRef("Edm.Guid")),
            },
            nav_properties={
                "Orders": EdmNavigationProperty(
                    name="Orders",
                    target_type=TypeRef("NS.Order", is_collection=True),
                    target_fk="CustomerId",
                ),
                "BestOrder": EdmNavigationProperty(
                    name="BestOrder",
                    target_type=TypeRef("NS.Order", is_collection=False),
                    source_fk="OwnerId",
                ),
            },
            key_properties=("Id",),
        )
        model.add_type(customer)

        model.add_type(
            EdmType(
                name="NS.Order",
                kind="entity",
                properties={
                    "Id": EdmProperty(name="Id", type=TypeRef("Edm.Guid")),
                    "CustomerId": EdmProperty(name="CustomerId", type=TypeRef("Edm.Guid")),
                    "Total": EdmProperty(name="Total", type=TypeRef("Edm.Decimal")),
                },
                key_properties=("Id",),
            )
        )

        model.add_entity_set(EntitySet(name="Customers", type=TypeRef("NS.Customer", is_collection=True)))
        model.add_entity_set(
            EntitySet(name="Me", type=TypeRef("NS.Customer"), is_singleton=True)
        )

        self.model = model
        self.checker = SemanticChecker(model)
        self.base = ValueType("NS.Customer", is_collection=False)

    def test_value_type_and_structured_type_resolution(self) -> None:
        self.assertEqual(ValueType("NS.Customer", True).element(), ValueType("NS.Customer", False))
        self.assertEqual(self.checker._get_structured_type("NS.Customer").name, "NS.Customer")  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._get_structured_type("Edm.String")  # pylint: disable=protected-access

    def test_infer_expr_type_literals_and_core_expression_forms(self) -> None:
        infer = self.checker._infer_expr_type  # pylint: disable=protected-access

        self.assertEqual(infer(Literal(None), self.base, {}), ValueType("Edm.Null"))
        self.assertEqual(infer(Literal(True), self.base, {}), ValueType("Edm.Boolean"))
        self.assertEqual(infer(Literal(1), self.base, {}), ValueType("Edm.Int64"))
        self.assertEqual(infer(Literal(1.5), self.base, {}), ValueType("Edm.Double"))
        self.assertEqual(infer(Literal(decimal.Decimal("1.2")), self.base, {}), ValueType("Edm.Decimal"))
        self.assertEqual(infer(Literal("x"), self.base, {}), ValueType("Edm.String"))
        self.assertEqual(infer(Literal(uuid.uuid4()), self.base, {}), ValueType("Edm.Guid"))
        self.assertEqual(infer(Literal(b"x"), self.base, {}), ValueType("Edm.Binary"))
        self.assertEqual(
            infer(Literal(datetime.datetime.now(datetime.timezone.utc)), self.base, {}),
            ValueType("Edm.DateTimeOffset"),
        )
        self.assertEqual(infer(Literal(datetime.date.today()), self.base, {}), ValueType("Edm.Date"))
        self.assertEqual(infer(Literal(datetime.time(12, 0)), self.base, {}), ValueType("Edm.TimeOfDay"))
        self.assertEqual(
            infer(Literal(datetime.timedelta(seconds=1)), self.base, {}),
            ValueType("Edm.Duration"),
        )
        self.assertEqual(infer(Literal({"a": 1}), self.base, {}), ValueType("Json.Object"))
        self.assertEqual(infer(Literal([1]), self.base, {}), ValueType("Json.Array"))

        class _Custom:  # pylint: disable=too-few-public-methods
            pass

        self.assertEqual(infer(Literal(_Custom()), self.base, {}), ValueType("Python._Custom"))

        self.assertEqual(
            infer(EnumLiteral("NS.Color", ["Red"]), self.base, {}),
            ValueType("NS.Color"),
        )
        self.assertEqual(
            infer(SpatialLiteral(is_geography=True, srid=4326, wkt="POINT(0 0)"), self.base, {}),
            ValueType("Edm.Geography"),
        )
        self.assertEqual(
            infer(SpatialLiteral(is_geography=False, srid=None, wkt="POINT(0 0)"), self.base, {}),
            ValueType("Edm.Geometry"),
        )

        self.assertEqual(infer(parse_rgql_expr("Name"), self.base, {}), ValueType("Edm.String"))
        self.assertEqual(
            infer(parse_rgql_expr("BestOrder"), self.base, {}),
            ValueType("NS.Order", is_collection=False),
        )
        self.assertEqual(
            infer(parse_rgql_expr("Address/Street"), self.base, {}),
            ValueType("Edm.String"),
        )
        self.assertEqual(
            infer(parse_rgql_expr("-Age"), self.base, {}),
            ValueType("Edm.Int32"),
        )
        self.assertEqual(infer(parse_rgql_expr("Age add 1"), self.base, {}), ValueType("Edm.Int32"))
        self.assertEqual(infer(parse_rgql_expr("Age eq 1"), self.base, {}), ValueType("Edm.Boolean"))
        self.assertEqual(infer(parse_rgql_expr("Name in ('A','B')"), self.base, {}), ValueType("Edm.Boolean"))
        self.assertEqual(infer(parse_rgql_expr("length(Name)"), self.base, {}), ValueType("Edm.Int32"))
        self.assertEqual(infer(parse_rgql_expr("contains(Name,'A')"), self.base, {}), ValueType("Edm.Boolean"))
        self.assertEqual(infer(parse_rgql_expr("custom(Name)"), self.base, {}), ValueType("Edm.String"))
        self.assertEqual(infer(parse_rgql_expr("custom()"), self.base, {}), ValueType("Edm.Null"))
        self.assertEqual(infer(parse_rgql_expr("Orders/any()"), self.base, {}), ValueType("Edm.Boolean"))
        self.assertEqual(
            infer(parse_rgql_expr("Orders/any(o:o/Total gt 10)"), self.base, {}),
            ValueType("Edm.Boolean"),
        )
        self.assertEqual(infer(parse_rgql_expr("cast(NS.Customer)"), self.base, {}), ValueType("NS.Customer"))
        self.assertEqual(infer(parse_rgql_expr("isof(NS.Customer)"), self.base, {}), ValueType("Edm.Boolean"))

        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("Missing"), self.base, {})
        with self.assertRaises(SemanticError):
            infer(MemberAccess(Literal(1), "x"), self.base, {})
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("Address/Missing"), self.base, {})
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("Name/any()"), self.base, {})
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("Tags in ('A')"), self.base, {})
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("Name in 1"), self.base, {})
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("Name in ([1])"), self.base, {})
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("Address has 'x'"), self.base, {})

    def test_identifier_filter_and_orderby_capability_checks(self) -> None:
        infer = self.checker._infer_expr_type  # pylint: disable=protected-access

        self.checker._expr_context = "filter"  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("SortOnly"), self.base, {})

        self.checker._expr_context = "orderby"  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("FilterOnly"), self.base, {})

        self.checker._expr_context = None  # pylint: disable=protected-access

    def test_literal_coercion_enum_json_and_primitive_validation(self) -> None:
        maybe = self.checker._maybe_coerce_literal  # pylint: disable=protected-access

        maybe(Literal("Red"), ValueType("NS.Color"))
        with self.assertRaises(SemanticError):
            maybe(Literal("Green"), ValueType("NS.Color"))

        maybe(Literal({"Street": "Main"}), ValueType("NS.Address"))
        maybe(Literal([{"Street": "Main"}]), ValueType("NS.Address", is_collection=True))
        with self.assertRaises(SemanticError):
            maybe(Literal({"Unknown": 1}), ValueType("NS.Address"))

        maybe(Literal({"any": "shape"}), ValueType("Edm.Untyped"))
        maybe(Literal("x"), ValueType("Edm.String"))

        with self.assertRaises(SemanticError):
            maybe(Literal(1), ValueType("Edm.Boolean"))
        with self.assertRaises(SemanticError):
            maybe(Literal("not-guid"), ValueType("Edm.Guid"))

        check_primitive = self.checker._check_primitive_literal_against_type  # pylint: disable=protected-access
        check_primitive(True, ValueType("Edm.Boolean"))
        check_primitive(uuid.uuid4(), ValueType("Edm.Guid"))
        check_primitive(datetime.date.today(), ValueType("Edm.Date"))
        check_primitive(datetime.time(12, 0), ValueType("Edm.TimeOfDay"))
        check_primitive(datetime.timedelta(seconds=1), ValueType("Edm.Duration"))
        check_primitive(123, ValueType("Edm.Int32"))
        check_primitive("anything", ValueType("NonEdm.Custom"))

        with self.assertRaises(SemanticError):
            check_primitive("x", ValueType("Edm.Boolean"))
        with self.assertRaises(SemanticError):
            check_primitive(1, ValueType("Edm.String"))
        with self.assertRaises(SemanticError):
            check_primitive("x", ValueType("Edm.Binary"))
        with self.assertRaises(SemanticError):
            check_primitive("x", ValueType("Edm.Guid"))
        with self.assertRaises(SemanticError):
            check_primitive("x", ValueType("Edm.Stream"))
        with self.assertRaises(SemanticError):
            check_primitive("x", ValueType("Edm.DateTimeOffset"))
        with self.assertRaises(SemanticError):
            check_primitive(datetime.datetime.now(), ValueType("Edm.Date"))
        with self.assertRaises(SemanticError):
            check_primitive("x", ValueType("Edm.TimeOfDay"))
        with self.assertRaises(SemanticError):
            check_primitive("x", ValueType("Edm.Duration"))
        with self.assertRaises(SemanticError):
            check_primitive("x", ValueType("Edm.Int32"))
        with self.assertRaises(SemanticError):
            check_primitive(256, ValueType("Edm.Byte"))
        with self.assertRaises(SemanticError):
            check_primitive(-129, ValueType("Edm.SByte"))
        with self.assertRaises(SemanticError):
            check_primitive(40000, ValueType("Edm.Int16"))
        with self.assertRaises(SemanticError):
            check_primitive(2**31, ValueType("Edm.Int32"))
        with self.assertRaises(SemanticError):
            check_primitive(2**63, ValueType("Edm.Int64"))

    def test_resource_path_and_key_resolution(self) -> None:
        check_path = self.checker._check_resource_path  # pylint: disable=protected-access

        with self.assertRaises(SemanticError):
            check_path([])
        with self.assertRaises(SemanticError):
            check_path([RGQLPathSegment(name="MissingSet")])

        self.assertEqual(
            check_path([RGQLPathSegment(name="Customers")]),
            ValueType("NS.Customer", is_collection=True),
        )

        guid_val = uuid.uuid4()
        self.assertEqual(
            check_path(
                [
                    RGQLPathSegment(
                        name="Customers",
                        key_components=[KeyComponent(name=None, expr=Literal(guid_val))],
                    )
                ]
            ),
            ValueType("NS.Customer", is_collection=False),
        )

        with self.assertRaises(SemanticError):
            check_path([RGQLPathSegment(name="Me", key_predicate="1")])

        self.assertEqual(
            check_path(
                [
                    RGQLPathSegment(name="Customers"),
                    RGQLPathSegment(name="$count", is_count=True),
                ]
            ),
            ValueType("Edm.Int64", is_collection=False),
        )

        with self.assertRaises(SemanticError):
            check_path(
                [
                    RGQLPathSegment(
                        name="Customers",
                        key_components=[KeyComponent(name=None, expr=Literal(uuid.uuid4()))],
                    ),
                    RGQLPathSegment(name="$count", is_count=True),
                ]
            )

        # Key-as-segment on single-key entity collection.
        self.assertEqual(
            check_path(
                [
                    RGQLPathSegment(name="Customers"),
                    RGQLPathSegment(name=str(uuid.uuid4())),
                ]
            ).is_collection,
            False,
        )

    def test_query_options_and_compute_checks(self) -> None:
        q = RGQLQueryOptions(
            filter=parse_rgql_expr("true"),
            orderby=parse_orderby("Name asc"),
            select=["Name"],
            expand=[ExpandItem(path="Orders")],
            apply=[IdentityTransform()],
            compute=[ComputeExpression(parse_rgql_expr("Name"), "NameCopy")],
            top=1,
            skip=2,
            param_aliases={"@p1": Literal(1)},
        )

        alias_env = self.checker._build_alias_env(self.base, q)  # pylint: disable=protected-access
        self.assertEqual(alias_env["@p1"], ValueType("Edm.Int64"))
        self.checker._check_query_options(self.base, q, alias_env)  # pylint: disable=protected-access

        with self.assertRaises(SemanticError):
            self.checker._check_query_options(  # pylint: disable=protected-access
                self.base,
                RGQLQueryOptions(top=-1),
                {},
            )
        with self.assertRaises(SemanticError):
            self.checker._check_query_options(  # pylint: disable=protected-access
                self.base,
                RGQLQueryOptions(skip=-1),
                {},
            )

        with self.assertRaises(SemanticError):
            self.checker._check_compute(  # pylint: disable=protected-access
                [
                    ComputeExpression(parse_rgql_expr("Name"), "X"),
                    ComputeExpression(parse_rgql_expr("Age"), "X"),
                ],
                self.base,
                {},
            )

    def test_expand_resolution_and_validation_helpers(self) -> None:
        self.assertEqual(
            self.checker._materialize_expand_items([], self.base),  # pylint: disable=protected-access
            [],
        )

        wildcard = ExpandItem(path="*", expand=[ExpandItem(path="*")], is_ref=True)
        materialized = self.checker._materialize_expand_items([wildcard], self.base)  # pylint: disable=protected-access
        self.assertEqual({item.path for item in materialized}, {"Orders", "BestOrder"})
        self.assertTrue(all(item.is_ref for item in materialized))
        self.assertTrue(all(item.expand == [] for item in materialized))

        explicit = self.checker._materialize_expand_items(  # pylint: disable=protected-access
            [ExpandItem(path="Orders", expand=[ExpandItem(path="*")])],
            self.base,
        )
        self.assertEqual(explicit[0].path, "Orders")
        self.assertEqual(explicit[0].expand, [])

        self.assertEqual(
            self.checker._resolve_expand_target_type(self.base, "Orders"),  # pylint: disable=protected-access
            ValueType("NS.Order", is_collection=True),
        )
        self.assertEqual(
            self.checker._resolve_expand_target_type(self.base, "NS.Order"),  # pylint: disable=protected-access
            ValueType("NS.Order", is_collection=False),
        )
        self.assertEqual(
            self.checker._resolve_expand_target_type(self.base, "Orders/NS.Order"),  # pylint: disable=protected-access
            ValueType("NS.Order", is_collection=True),
        )
        with self.assertRaises(SemanticError):
            self.checker._resolve_expand_target_type(self.base, "")  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._resolve_expand_target_type(self.base, "Name")  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._resolve_expand_target_type(self.base, "NS.Color")  # pylint: disable=protected-access

        self.checker._check_expand([ExpandItem(path="*")], self.base, {})  # pylint: disable=protected-access

        valid = ExpandItem(
            path="Orders",
            filter=parse_rgql_expr("Total gt 1"),
            orderby=parse_orderby("Total desc"),
            select=["Total"],
            expand=[ExpandItem(path="*")],
            top=1,
            skip=0,
            levels="max",
        )
        self.checker._check_expand_item(valid, self.base, {})  # pylint: disable=protected-access

        with self.assertRaises(SemanticError):
            self.checker._check_expand_item(  # pylint: disable=protected-access
                ExpandItem(path="Orders", top=-1),
                self.base,
                {},
            )
        with self.assertRaises(SemanticError):
            self.checker._check_expand_item(  # pylint: disable=protected-access
                ExpandItem(path="Orders", skip=-1),
                self.base,
                {},
            )
        with self.assertRaises(SemanticError):
            self.checker._check_expand_item(  # pylint: disable=protected-access
                ExpandItem(path="Orders", levels=0),
                self.base,
                {},
            )

    def test_orderby_filter_and_member_access_additional_branches(self) -> None:
        self.checker._check_select(["Address/Street"], self.base)  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._resolve_property_path(self.base, "")  # pylint: disable=protected-access

        self.checker._check_orderby(parse_orderby("Name asc"), self.base, {})  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._check_orderby(parse_orderby("Tags asc"), self.base, {})  # pylint: disable=protected-access

        self.checker._check_filter_expr(parse_rgql_expr("true"), self.base, {})  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._check_filter_expr(parse_rgql_expr("1"), self.base, {})  # pylint: disable=protected-access

        self.model.get_type("NS.Address").properties["NoSort"] = EdmProperty(
            name="NoSort",
            type=TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        )
        infer = self.checker._infer_expr_type  # pylint: disable=protected-access

        self.checker._expr_context = "filter"  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            infer(MemberAccess(Identifier("Address"), "NoSort"), self.base, {})

        self.checker._expr_context = "orderby"  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            infer(MemberAccess(Identifier("Address"), "NoSort"), self.base, {})
        self.checker._expr_context = None  # pylint: disable=protected-access

        self.assertEqual(
            infer(parse_rgql_expr("true and false"), self.base, {}),
            ValueType("Edm.Boolean"),
        )
        self.assertEqual(
            infer(parse_rgql_expr("Name in Tags"), self.base, {}),
            ValueType("Edm.Boolean"),
        )
        with self.assertRaises(SemanticError):
            infer(parse_rgql_expr("Age in Tags"), self.base, {})
        self.assertEqual(
            infer(parse_rgql_expr("'x' eq Name"), self.base, {}),
            ValueType("Edm.Boolean"),
        )
        self.assertEqual(
            infer(BinaryOp("custom", Identifier("Age"), Literal(1)), self.base, {}),
            ValueType("Edm.Int32"),
        )
        self.assertEqual(
            infer(parse_rgql_expr("tolower(Name)"), self.base, {}),
            ValueType("Edm.String"),
        )
        with self.assertRaises(SemanticError):
            infer(object(), self.base, {})  # type: ignore[arg-type]

    def test_literal_and_apply_additional_branches(self) -> None:
        check_primitive = self.checker._check_primitive_literal_against_type  # pylint: disable=protected-access

        check_primitive(None, ValueType("Edm.String"))
        check_primitive(True, ValueType("Edm.Byte"))
        check_primitive(255, ValueType("Edm.Byte"))
        check_primitive(-128, ValueType("Edm.SByte"))
        check_primitive(32767, ValueType("Edm.Int16"))
        check_primitive(2**31 - 1, ValueType("Edm.Int32"))
        check_primitive(2**63 - 1, ValueType("Edm.Int64"))
        check_primitive("spatial-ok", ValueType("Edm.GeographyPoint"))
        check_primitive("any", ValueType("Edm.Untyped"))

        self.checker._check_enum_literal(  # pylint: disable=protected-access
            "Anything",
            EdmType(name="NS.EmptyEnum", kind="enum", enum_members=set()),
        )

        with self.assertRaises(SemanticError):
            self.checker._check_json_literal_against_type({}, ValueType("Edm.String"))  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._check_json_literal_against_type(  # pylint: disable=protected-access
                {},
                ValueType("NS.Address", is_collection=True),
            )
        with self.assertRaises(SemanticError):
            self.checker._check_json_literal_against_type(  # pylint: disable=protected-access
                [1],
                ValueType("NS.Address", is_collection=True),
            )
        with self.assertRaises(SemanticError):
            self.checker._check_json_literal_against_type(  # pylint: disable=protected-access
                [],
                ValueType("NS.Address"),
            )

        self.model.add_type(
            EdmType(
                name="NS.Wrapper",
                kind="complex",
                properties={
                    "Inner": EdmProperty(name="Inner", type=TypeRef("NS.Address"))
                },
            )
        )
        self.checker._check_json_literal_against_type(  # pylint: disable=protected-access
            {"Inner": {"Street": "Main"}},
            ValueType("NS.Wrapper"),
        )

        self.checker._ensure_enum_for_has(ValueType("NS.Color"))  # pylint: disable=protected-access
        self.checker._ensure_enum_for_has(ValueType("NS.Unknown"))  # pylint: disable=protected-access

        with self.assertRaises(SemanticError):
            self.checker._ensure_enum_for_has(ValueType("NS.Address"))  # pylint: disable=protected-access

    def test_apply_transform_validation_paths(self) -> None:
        current = ValueType("NS.Customer", is_collection=False)

        # Covers _check_apply loop.
        self.checker._check_apply(  # pylint: disable=protected-access
            [IdentityTransform(), TopTransform(1)],
            current,
            {},
        )

        self.assertEqual(
            self.checker._check_apply_transform(IdentityTransform(), current, {}),  # pylint: disable=protected-access
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(  # pylint: disable=protected-access
                FilterTransform(parse_rgql_expr("true")),
                current,
                {},
            ),
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(  # pylint: disable=protected-access
                OrderByTransform(parse_orderby("Name asc")),
                current,
                {},
            ),
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(  # pylint: disable=protected-access
                SearchTransform(search=object()),
                current,
                {},
            ),
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(ComputeTransform([ComputeExpression(parse_rgql_expr("Name"), "X")]), current, {}),  # pylint: disable=protected-access
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(
                AggregateTransform([AggregateExpression(expr=Literal(1), method="sum", alias="S")]),
                current,
                {},
            ),  # pylint: disable=protected-access
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(  # pylint: disable=protected-access
                AggregateTransform(
                    [AggregateExpression(expr=None, method=None, alias="Count", is_count=True)]
                ),
                current,
                {},
            ),
            current,
        )

        with self.assertRaises(SemanticError):
            self.checker._check_apply_transform(SkipTransform(-1), current, {})  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._check_apply_transform(TopTransform(-1), current, {})  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._check_apply_transform(
                AggregateTransform([AggregateExpression(expr=None, method="sum", alias="S", is_count=False)]),
                current,
                {},
            )  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._check_apply_transform(
                AggregateTransform([AggregateExpression(expr=parse_rgql_expr("Tags"), method="sum", alias="S")]),
                current,
                {},
            )  # pylint: disable=protected-access
        with self.assertRaises(SemanticError):
            self.checker._check_apply_transform(
                GroupByTransform(grouping_paths=["Missing"]),
                current,
                {},
            )  # pylint: disable=protected-access

        self.assertEqual(
            self.checker._check_apply_transform(
                GroupByTransform(
                    grouping_paths=["Name"],
                    sub_transforms=[IdentityTransform()],
                ),
                current,
                {},
            ),  # pylint: disable=protected-access
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(
                BottomTopTransform(
                    kind="topcount",
                    n_expr=Literal(1),
                    value_expr=parse_rgql_expr("Age"),
                ),
                current,
                {},
            ),  # pylint: disable=protected-access
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(
                ConcatTransform(sequences=[[IdentityTransform()]]),
                current,
                {},
            ),  # pylint: disable=protected-access
            current,
        )
        self.assertEqual(
            self.checker._check_apply_transform(
                CustomApplyTransform(name="x", raw_args="y"),
                current,
                {},
            ),  # pylint: disable=protected-access
            current,
        )

        with self.assertRaises(SemanticError):
            self.checker._check_apply_transform(_UnknownTransform(), current, {})  # pylint: disable=protected-access


if __name__ == "__main__":
    unittest.main()
