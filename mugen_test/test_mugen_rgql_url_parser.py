"""Unit tests for RGQL URL parser."""

import unittest
from unittest.mock import patch

from mugen.core.utility.rgql.ast import BinaryOp, Identifier, Literal
from mugen.core.utility.rgql.expr_parser import ParseError
from mugen.core.utility.rgql.url_parser import (
    ExpandItem,
    KeyComponent,
    _parse_expand_options,
    _parse_key_predicate,
    _parse_path,
    _split_commas_top_level,
    _split_expand_item,
    _split_semicolons_top_level,
    _split_top_level,
    parse_expand,
    parse_rgql_url,
)


class TestMugenRgqlUrlParser(unittest.TestCase):
    """Covers URL parser helper functions and main parse path."""

    def test_split_top_level_helpers(self) -> None:
        self.assertEqual(
            _split_top_level("a,b(c,d),{'k':[1,2]},'x,y',z", ","),
            ["a", "b(c,d)", "{'k':[1,2]}", "'x,y'", "z"],
        )
        self.assertEqual(
            _split_top_level("a,'it''s,fine',b", ","),
            ["a", "'it''s,fine'", "b"],
        )
        self.assertEqual(_split_top_level("", ","), [])
        self.assertEqual(_split_commas_top_level("a,,b, "), ["a", "b"])
        self.assertEqual(
            _split_semicolons_top_level("a;fn(x;y);'q;w';b"),
            ["a", "fn(x;y)", "'q;w'", "b"],
        )

    def test_split_expand_item(self) -> None:
        path, opts = _split_expand_item("Orders($filter=true;$top=1)")
        self.assertEqual(path, "Orders")
        self.assertEqual(opts, "$filter=true;$top=1")

        self.assertEqual(_split_expand_item("Orders"), ("Orders", None))

        with self.assertRaises(ParseError):
            _split_expand_item("Orders($top=1))")
        with self.assertRaises(ParseError):
            _split_expand_item("Orders)")
        with self.assertRaises(ParseError):
            _split_expand_item("Orders($top=1")
        with self.assertRaises(ParseError):
            _split_expand_item("Orders($top=1)junk")
        with self.assertRaises(ParseError):
            _split_expand_item("Orders($filter=Name eq 'it''s (ok)')")

    def test_parse_key_predicate(self) -> None:
        self.assertEqual(
            _parse_key_predicate("1"),
            [KeyComponent(name=None, expr=Literal(1))],
        )
        self.assertEqual(
            _parse_key_predicate("OrderId=1,ProductId='P1'"),
            [
                KeyComponent(name="OrderId", expr=Literal(1)),
                KeyComponent(name="ProductId", expr=Literal("P1")),
            ],
        )

        with self.assertRaises(ParseError):
            _parse_key_predicate("")
        with self.assertRaises(ParseError):
            _parse_key_predicate("=1")
        with self.assertRaises(ParseError):
            _parse_key_predicate("OrderId=(")
        with patch(
            "mugen.core.utility.rgql.url_parser._split_commas_top_level",
            return_value=["OrderId=1", ""],
        ):
            with self.assertRaises(ParseError):
                _parse_key_predicate("OrderId=1,")

    def test_parse_expand_with_options_and_ref(self) -> None:
        items = parse_expand(
            "Orders/$ref,Orders("
            "$filter=true;"
            "$orderby=Name desc;"
            "$select=Id,Name;"
            "$expand=Items($top=1);"
            "$top=5;"
            "$skip=2;"
            "$count=true;"
            "$search=alpha;"
            "$levels=max"
            ")"
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].path, "Orders")
        self.assertTrue(items[0].is_ref)
        self.assertEqual(items[1].path, "Orders")
        self.assertFalse(items[1].is_ref)
        self.assertEqual(items[1].top, 5)
        self.assertEqual(items[1].skip, 2)
        self.assertEqual(items[1].count, True)
        self.assertEqual(items[1].levels, "max")
        self.assertEqual(items[1].select, ["Id", "Name"])
        self.assertIsNotNone(items[1].filter)
        self.assertIsNotNone(items[1].orderby)
        self.assertIsNotNone(items[1].expand)
        self.assertIsNotNone(items[1].search)

    def test_parse_expand_option_errors(self) -> None:
        with self.assertRaises(ParseError):
            parse_expand("Orders($top=abc)")
        with self.assertRaises(ParseError):
            parse_expand("Orders($skip=abc)")
        with self.assertRaises(ParseError):
            parse_expand("Orders($count=maybe)")
        with self.assertRaises(ParseError):
            parse_expand("Orders($levels=abc)")
        with self.assertRaises(ParseError):
            parse_expand("Orders($filter=1)")
        with self.assertRaises(ParseError):
            parse_expand("Orders($unknown=1)")
        with self.assertRaises(ParseError):
            parse_expand("($top=1)")
        with self.assertRaises(ParseError):
            parse_expand("Orders($top)")
        parsed = parse_expand("Orders(top=1;count=false)")
        self.assertEqual(parsed[0].top, 1)
        self.assertEqual(parsed[0].count, False)

    def test_parse_expand_options_private_helper_empty(self) -> None:
        item = ExpandItem(path="Orders")
        _parse_expand_options(item, "")
        self.assertIsNone(item.top)
        with patch(
            "mugen.core.utility.rgql.url_parser._split_semicolons_top_level",
            return_value=["", "top=1"],
        ):
            _parse_expand_options(item, "top=1")
        self.assertEqual(item.top, 1)
        with patch(
            "mugen.core.utility.rgql.url_parser._split_commas_top_level",
            return_value=["", "Orders"],
        ):
            parsed = parse_expand("Orders")
        self.assertEqual(len(parsed), 1)

    def test_parse_path(self) -> None:
        path = _parse_path("/Customers(1)/Orders/$count")
        self.assertEqual(path[0].name, "Customers")
        self.assertEqual(path[0].key_predicate, "1")
        self.assertEqual(path[1].name, "Orders")
        self.assertEqual(path[2].name, "$count")
        self.assertTrue(path[2].is_count)

        composite = _parse_path("/OrderItems(OrderId=1,ProductId=2)")
        self.assertEqual(composite[0].name, "OrderItems")
        self.assertEqual(len(composite[0].key_components or []), 2)

        with self.assertRaises(ParseError):
            _parse_path("/Customers()")

    def test_parse_rgql_url_success(self) -> None:
        url = (
            "/Customers(1)?"
            "$filter=true&"
            "$orderby=Name%20desc&"
            "$select=Id,Name&"
            "$expand=Orders($top=1)&"
            "$search=alpha&"
            "$top=10&"
            "$skip=5&"
            "$count=true&"
            "$format=json&"
            "$skiptoken=s1&"
            "$deltatoken=d1&"
            "$schemaversion=v1&"
            "@p1=10&"
            "unknown=1"
        )
        parsed = parse_rgql_url(url)

        self.assertEqual(parsed.path, "/Customers(1)")
        self.assertEqual(parsed.resource_path[0].name, "Customers")
        self.assertIsNotNone(parsed.query.filter)
        self.assertIsNotNone(parsed.query.orderby)
        self.assertEqual(parsed.query.select, ["Id", "Name"])
        self.assertIsNotNone(parsed.query.expand)
        self.assertIsNotNone(parsed.query.search)
        self.assertEqual(parsed.query.top, 10)
        self.assertEqual(parsed.query.skip, 5)
        self.assertEqual(parsed.query.count, True)
        self.assertEqual(parsed.query.format, "json")
        self.assertEqual(parsed.query.skiptoken, "s1")
        self.assertEqual(parsed.query.deltatoken, "d1")
        self.assertEqual(parsed.query.schemaversion, "v1")
        self.assertEqual(parsed.query.param_aliases["@p1"], Literal(10))

    def test_parse_rgql_url_alias_errors(self) -> None:
        with self.assertRaises(ParseError):
            parse_rgql_url("/Customers?@p1=")
        with self.assertRaises(ParseError):
            parse_rgql_url("/Customers?@p1=1&@p1=2")

    def test_parse_rgql_url_filter_and_paging_errors(self) -> None:
        with self.assertRaises(ParseError):
            parse_rgql_url("/Customers?$filter=1")
        with self.assertRaises(ParseError):
            parse_rgql_url("/Customers?$top=abc")
        with self.assertRaises(ParseError):
            parse_rgql_url("/Customers?$skip=abc")
        with self.assertRaises(ParseError):
            parse_rgql_url("/Customers?$count=maybe")

    def test_parse_rgql_url_duplicate_option_errors(self) -> None:
        duplicate_queries = [
            "$filter=true&$filter=false",
            "$orderby=Name&$orderby=Id",
            "$select=Id&$select=Name",
            "$expand=Orders&$expand=Items",
            "$search=a&$search=b",
            "$top=1&$top=2",
            "$skip=1&$skip=2",
            "$count=true&$count=false",
            "$format=json&$format=xml",
            "$skiptoken=s1&$skiptoken=s2",
            "$deltatoken=d1&$deltatoken=d2",
            "$schemaversion=v1&$schemaversion=v2",
        ]
        for query in duplicate_queries:
            with self.subTest(query=query):
                with self.assertRaises(ParseError):
                    parse_rgql_url(f"/Customers?{query}")

    def test_parse_rgql_url_apply_and_compute_duplicates(self) -> None:
        with (
            patch(
                "mugen.core.utility.rgql.url_parser.parse_apply",
                return_value=[],
            ),
            patch(
                "mugen.core.utility.rgql.url_parser.parse_compute_option",
                return_value=[],
            ),
        ):
            parsed = parse_rgql_url("/Customers?$apply=a&$compute=b")
            self.assertEqual(parsed.query.apply, [])
            self.assertEqual(parsed.query.compute, [])

            with self.assertRaises(ParseError):
                parse_rgql_url("/Customers?$apply=a&$apply=b")
            with self.assertRaises(ParseError):
                parse_rgql_url("/Customers?$compute=a&$compute=b")

    def test_case_insensitive_and_no_dollar_option_names(self) -> None:
        parsed = parse_rgql_url("/Customers?FILTER=true&Top=1&skip=2&Count=false")
        self.assertEqual(parsed.query.filter, Literal(True))
        self.assertEqual(parsed.query.top, 1)
        self.assertEqual(parsed.query.skip, 2)
        self.assertEqual(parsed.query.count, False)
        parsed = parse_rgql_url("/Customers?=ignored&$top=1")
        self.assertEqual(parsed.query.top, 1)

    def test_filter_boolean_shape_via_patch(self) -> None:
        with (
            patch(
                "mugen.core.utility.rgql.url_parser.parse_rgql_expr",
                return_value=BinaryOp("add", Identifier("a"), Literal(1)),
            ),
            patch(
                "mugen.core.utility.rgql.url_parser.is_boolean_expr",
                return_value=False,
            ),
        ):
            with self.assertRaises(ParseError):
                parse_rgql_url("/Customers?$filter=syntactic")
