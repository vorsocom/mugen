"""Unit tests for RGQL $apply parser."""

import unittest
from unittest.mock import patch

from mugen.core.utility.rgql.ast import BinaryOp, Identifier, Literal
from mugen.core.utility.rgql.expr_parser import ParseError
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
    _find_keyword_top_level,
    _match_closing_paren,
    _parse_aggregate,
    _parse_bottom_top,
    _parse_compute,
    _parse_concat,
    _parse_filter,
    _parse_groupby,
    _parse_identity,
    _parse_orderby_transform,
    _parse_search_transform,
    _parse_single_transform,
    _parse_skip,
    _parse_top,
    _split_apply_sequence,
    _split_commas_top_level,
    parse_apply,
    parse_compute_option,
)


class TestMugenRgqlApplyParser(unittest.TestCase):
    """Covers pipeline parsing, helper splitting, and error branches."""

    def test_split_helpers_respect_nested_structures_and_quotes(self) -> None:
        self.assertEqual(
            _split_apply_sequence("filter(Name eq 'it''s/ok')/compute({'k':[1,2]} as K)/top(1)"),
            ["filter(Name eq 'it''s/ok')", "compute({'k':[1,2]} as K)", "top(1)"],
        )
        self.assertEqual(_split_apply_sequence(" skip(1) // top(2) "), ["skip(1)", "top(2)"])
        self.assertEqual(_split_apply_sequence("skip(1)/   "), ["skip(1)"])
        self.assertEqual(_split_apply_sequence("x)/y"), ["x)", "y"])

        self.assertEqual(
            _split_commas_top_level("a, fn(b,c), {'k':[1,2]}, 'x,y', t"),
            ["a", "fn(b,c)", "{'k':[1,2]}", "'x,y'", "t"],
        )
        self.assertEqual(_split_commas_top_level("a,,b, "), ["a", "b"])
        self.assertEqual(_split_commas_top_level("'it''s,fine',x"), ["'it''s,fine'", "x"])

    def test_parse_apply_top_level_and_empty_errors(self) -> None:
        parsed = parse_apply("skip(1)/top(2)/identity()/Custom(raw)")
        self.assertEqual([type(x) for x in parsed], [SkipTransform, TopTransform, IdentityTransform, CustomApplyTransform])
        self.assertEqual(parsed[0], SkipTransform(count=1))
        self.assertEqual(parsed[1], TopTransform(count=2))
        self.assertEqual(parsed[2], IdentityTransform())
        self.assertEqual(parsed[3], CustomApplyTransform(name="Custom", raw_args="raw"))

        with self.assertRaises(ParseError):
            parse_apply("")

    def test_parse_single_transform_dispatches_all_known_forms(self) -> None:
        cases = [
            ("aggregate(Amount with sum as Total)", AggregateTransform),
            ("groupby((Category),top(1))", GroupByTransform),
            ("topcount(1,Amount)", BottomTopTransform),
            ("bottomcount(1,Amount)", BottomTopTransform),
            ("toppercent(1,Amount)", BottomTopTransform),
            ("bottompercent(1,Amount)", BottomTopTransform),
            ("topsum(1,Amount)", BottomTopTransform),
            ("bottomsum(1,Amount)", BottomTopTransform),
            ("filter(true)", FilterTransform),
            ("orderby(Name desc)", OrderByTransform),
            ("search(alpha)", SearchTransform),
            ("skip(1)", SkipTransform),
            ("top(1)", TopTransform),
            ("identity()", IdentityTransform),
            ("compute(Price as P)", ComputeTransform),
            ("concat(top(1),skip(1))", ConcatTransform),
        ]
        for text, expected_type in cases:
            with self.subTest(text=text):
                parsed = _parse_single_transform(text)
                self.assertIsInstance(parsed, expected_type)

        custom = _parse_single_transform("my_transform(abc)")
        self.assertEqual(custom, CustomApplyTransform(name="my_transform", raw_args="abc"))

        with self.assertRaises(ParseError):
            _parse_single_transform("")
        with self.assertRaises(ParseError):
            _parse_single_transform("skip")

    def test_parse_aggregate_variants_and_errors(self) -> None:
        parsed = _parse_aggregate("Amount with sum as Total, Amount with min, $count as Count")
        self.assertEqual(
            parsed,
            AggregateTransform(
                aggregates=[
                    AggregateExpression(
                        expr=Identifier("Amount"),
                        method="sum",
                        alias="Total",
                        is_count=False,
                    ),
                    AggregateExpression(
                        expr=Identifier("Amount"),
                        method="min",
                        alias=None,
                        is_count=False,
                    ),
                    AggregateExpression(expr=None, method=None, alias="Count", is_count=True),
                ]
            ),
        )

        with patch(
            "mugen.core.utility.rgql.apply_parser._split_commas_top_level",
            return_value=["Amount with max as M", ""],
        ):
            patched = _parse_aggregate("ignored")
        self.assertEqual(len(patched.aggregates), 1)

        with self.assertRaises(ParseError):
            _parse_aggregate("")
        with self.assertRaises(ParseError):
            _parse_aggregate("$count")
        with self.assertRaises(ParseError):
            _parse_aggregate("$count as ")
        with self.assertRaises(ParseError):
            _parse_aggregate("Amount")
        with self.assertRaises(ParseError):
            _parse_aggregate("Amount with")
        with self.assertRaises(ParseError):
            _parse_aggregate("Amount with sum as")

    def test_find_keyword_top_level(self) -> None:
        self.assertEqual(_find_keyword_top_level("Amount with sum as Total", "with"), 7)
        self.assertEqual(_find_keyword_top_level("basis as Alias", "as"), 6)
        self.assertEqual(_find_keyword_top_level("fn(a as b) as Alias", "as"), 11)
        self.assertEqual(_find_keyword_top_level("'a''s as x' as Alias", "as"), 12)
        self.assertIsNone(_find_keyword_top_level("basis", "as"))

    def test_groupby_and_parenthesis_matching(self) -> None:
        parsed = _parse_groupby("(Category, Region),aggregate(Amount with sum as Total)")
        self.assertEqual(parsed.grouping_paths, ["Category", "Region"])
        self.assertIsNotNone(parsed.sub_transforms)
        self.assertEqual(len(parsed.sub_transforms or []), 1)

        self.assertEqual(_parse_groupby("(Category)"), GroupByTransform(grouping_paths=["Category"], sub_transforms=None))

        self.assertEqual(_match_closing_paren("(a('x''y'))", 0), 10)
        self.assertIsNone(_match_closing_paren("abc", 0))
        self.assertIsNone(_match_closing_paren("(abc", 0))

        with self.assertRaises(ParseError):
            _parse_groupby("Category")
        with self.assertRaises(ParseError):
            _parse_groupby("(Category")
        with self.assertRaises(ParseError):
            _parse_groupby("(Category)top(1)")

    def test_bottom_top_filter_orderby_search_skip_top_and_identity(self) -> None:
        self.assertEqual(
            _parse_bottom_top("topcount", "5,Amount"),
            BottomTopTransform(kind="topcount", n_expr=Literal(5), value_expr=Identifier("Amount")),
        )
        with self.assertRaises(ParseError):
            _parse_bottom_top("topcount", "5")

        self.assertEqual(_parse_filter("true"), FilterTransform(predicate=Literal(True)))
        with self.assertRaises(ParseError):
            _parse_filter("1")

        orderby = _parse_orderby_transform("Name desc")
        self.assertIsInstance(orderby, OrderByTransform)
        self.assertEqual(len(orderby.items), 1)
        self.assertEqual(orderby.items[0].direction, "desc")

        search = _parse_search_transform("alpha")
        self.assertIsInstance(search, SearchTransform)

        self.assertEqual(_parse_skip("2"), SkipTransform(count=2))
        self.assertEqual(_parse_top("3"), TopTransform(count=3))
        self.assertEqual(_parse_identity(""), IdentityTransform())

        with self.assertRaises(ParseError):
            _parse_skip("abc")
        with self.assertRaises(ParseError):
            _parse_skip("-1")
        with self.assertRaises(ParseError):
            _parse_top("abc")
        with self.assertRaises(ParseError):
            _parse_top("-1")
        with self.assertRaises(ParseError):
            _parse_identity("x")

    def test_compute_and_compute_option(self) -> None:
        parsed = _parse_compute("Price add 1 as Next, Name as Display")
        self.assertEqual(
            parsed,
            ComputeTransform(
                computes=[
                    ComputeExpression(
                        expr=BinaryOp("add", Identifier("Price"), Literal(1)),
                        alias="Next",
                    ),
                    ComputeExpression(expr=Identifier("Name"), alias="Display"),
                ]
            ),
        )

        self.assertEqual(
            parse_compute_option("Price as P"),
            [ComputeExpression(expr=Identifier("Price"), alias="P")],
        )

        with patch(
            "mugen.core.utility.rgql.apply_parser._split_commas_top_level",
            return_value=["Price as P", ""],
        ):
            patched = _parse_compute("ignored")
        self.assertEqual(len(patched.computes), 1)

        with self.assertRaises(ParseError):
            _parse_compute("")
        with self.assertRaises(ParseError):
            _parse_compute("Price")
        with self.assertRaises(ParseError):
            _parse_compute("Price as")

    def test_concat_parse_and_error_paths(self) -> None:
        parsed = _parse_concat("top(1)/skip(1), identity()")
        self.assertEqual(len(parsed.sequences), 2)
        self.assertEqual(len(parsed.sequences[0]), 2)
        self.assertEqual(parsed.sequences[1], [IdentityTransform()])

        with patch(
            "mugen.core.utility.rgql.apply_parser._split_commas_top_level",
            return_value=["top(1)", ""],
        ):
            patched = _parse_concat("ignored")
        self.assertEqual(len(patched.sequences), 1)

        with self.assertRaises(ParseError):
            _parse_concat("")


if __name__ == "__main__":
    unittest.main()
