"""Unit tests for RGQL-to-relational adapter helpers."""

import unittest

from mugen.core.contract.gateway.storage.rdbms.types import ScalarFilterOp, TextFilterOp
from mugen.core.utility.rgql.ast import Identifier, Literal, MemberAccess
from mugen.core.utility.rgql.expr_parser import parse_rgql_expr
from mugen.core.utility.rgql.orderby_parser import OrderByItem
from mugen.core.utility.rgql.url_parser import RGQLQueryOptions
from mugen.core.utility.rgql_helper.rgql_to_relational import (
    RGQLToRelationalAdapter,
    _is_literal,
    _literal_value,
    _prop_path,
    _prop_path_to_column,
)


class TestMugenRgqlToRelationalAdapter(unittest.TestCase):
    """Covers helper extraction, filter conversion, and ordering mapping."""

    def test_literal_and_property_path_helpers(self) -> None:
        self.assertTrue(_is_literal(Literal(1)))
        self.assertFalse(_is_literal(Identifier("Id")))

        self.assertEqual(_literal_value(Literal("x")), "x")
        with self.assertRaises(ValueError):
            _literal_value(Identifier("Id"))

        self.assertEqual(_prop_path(Identifier("UserId")), "UserId")
        self.assertEqual(
            _prop_path(
                MemberAccess(
                    MemberAccess(Identifier("Address"), "City"),
                    "PostalCode",
                )
            ),
            "Address/City/PostalCode",
        )
        self.assertEqual(_prop_path(MemberAccess(Literal(1), "OnlyMember")), "OnlyMember")
        with self.assertRaises(ValueError):
            _prop_path(Literal(1))

        self.assertEqual(_prop_path_to_column("UserId"), "user_id")
        self.assertEqual(_prop_path_to_column("Address/PostalCode"), "address_postal_code")

    def test_build_relational_query_maps_ordering_limit_and_offset(self) -> None:
        adapter = RGQLToRelationalAdapter()
        opts = RGQLQueryOptions(
            orderby=[
                OrderByItem(expr=Identifier("Name"), direction="desc"),
                OrderByItem(
                    expr=MemberAccess(Identifier("Address"), "City"),
                    direction="asc",
                ),
            ],
            top=10,
            skip=5,
        )

        groups, order_by, limit, offset = adapter.build_relational_query(opts)

        self.assertEqual(groups, [])
        self.assertEqual(len(order_by), 2)
        self.assertEqual(order_by[0].field, "name")
        self.assertTrue(order_by[0].descending)
        self.assertEqual(order_by[1].field, "address_city")
        self.assertFalse(order_by[1].descending)
        self.assertEqual(limit, 10)
        self.assertEqual(offset, 5)

        empty_groups, empty_order_by, empty_limit, empty_offset = adapter.build_relational_query(RGQLQueryOptions())
        self.assertEqual(empty_groups, [])
        self.assertEqual(list(empty_order_by), [])
        self.assertIsNone(empty_limit)
        self.assertIsNone(empty_offset)

        filtered_groups, _, _, _ = adapter.build_relational_query(
            RGQLQueryOptions(filter=parse_rgql_expr("Name eq 'Filtered'"))
        )
        self.assertEqual(len(filtered_groups), 1)

    def test_filter_to_groups_produces_dnf_or_groups(self) -> None:
        adapter = RGQLToRelationalAdapter()
        expr = parse_rgql_expr(
            "(Name eq 'A' and Age gt 1) or (Name eq 'B' and contains(Title,'x'))"
        )

        groups = adapter._filter_to_groups(expr)  # pylint: disable=protected-access
        self.assertEqual(len(groups), 2)

        self.assertEqual(groups[0].where, {"name": "A"})
        self.assertEqual(len(groups[0].scalar_filters), 1)
        self.assertEqual(groups[0].scalar_filters[0].op, ScalarFilterOp.GT)

        self.assertEqual(groups[1].where, {"name": "B"})
        self.assertEqual(len(groups[1].text_filters), 1)
        self.assertEqual(groups[1].text_filters[0].op, TextFilterOp.CONTAINS)

    def test_add_atom_supports_binary_scalar_operators(self) -> None:
        adapter = RGQLToRelationalAdapter()
        where = {}
        text_filters = []
        scalar_filters = []

        adapter._add_atom(parse_rgql_expr("Name eq 'Bob'"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        adapter._add_atom(parse_rgql_expr("Age ne 50"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        adapter._add_atom(parse_rgql_expr("Age gt 18"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        adapter._add_atom(parse_rgql_expr("Age ge 18"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        adapter._add_atom(parse_rgql_expr("Age lt 99"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        adapter._add_atom(parse_rgql_expr("Age le 99"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        adapter._add_atom(parse_rgql_expr("Age in (1,2,3)"), where, text_filters, scalar_filters)  # pylint: disable=protected-access

        self.assertEqual(where, {"name": "Bob"})
        self.assertEqual([sf.op for sf in scalar_filters], [
            ScalarFilterOp.NE,
            ScalarFilterOp.GT,
            ScalarFilterOp.GTE,
            ScalarFilterOp.LT,
            ScalarFilterOp.LTE,
            ScalarFilterOp.IN,
        ])

    def test_add_atom_supports_text_functions(self) -> None:
        adapter = RGQLToRelationalAdapter()
        where = {}
        text_filters = []
        scalar_filters = []

        adapter._add_atom(parse_rgql_expr("contains(Name,'smith')"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        adapter._add_atom(parse_rgql_expr("startswith(Code,'ABC')"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        adapter._add_atom(parse_rgql_expr("endswith(Sku,'xyz')"), where, text_filters, scalar_filters)  # pylint: disable=protected-access

        self.assertEqual(len(text_filters), 3)
        self.assertEqual([tf.op for tf in text_filters], [
            TextFilterOp.CONTAINS,
            TextFilterOp.STARTSWITH,
            TextFilterOp.ENDSWITH,
        ])
        self.assertTrue(all(tf.case_sensitive is False for tf in text_filters))

    def test_add_atom_error_paths(self) -> None:
        adapter = RGQLToRelationalAdapter()
        where = {}
        text_filters = []
        scalar_filters = []

        adapter._add_atom(parse_rgql_expr("Name eq 'Bob'"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            adapter._add_atom(parse_rgql_expr("Name eq 'Alice'"), where, text_filters, scalar_filters)  # pylint: disable=protected-access

        with self.assertRaises(ValueError):
            adapter._add_atom(parse_rgql_expr("Age gt OtherAge"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            adapter._add_atom(parse_rgql_expr("Age in 5"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            adapter._add_atom(parse_rgql_expr("contains(Name, Other)"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            adapter._add_atom(parse_rgql_expr("not (Name eq 'Bob')"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            adapter._add_atom(parse_rgql_expr("length(Name)"), where, text_filters, scalar_filters)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            adapter._add_atom(parse_rgql_expr("Age add 1"), where, text_filters, scalar_filters)  # pylint: disable=protected-access


if __name__ == "__main__":
    unittest.main()
