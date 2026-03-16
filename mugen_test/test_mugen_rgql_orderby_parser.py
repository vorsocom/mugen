"""Unit tests for RGQL orderby parsing."""

import unittest
from unittest.mock import patch

from mugen.core.utility.rgql.ast import Identifier
from mugen.core.utility.rgql.expr_parser import ParseError
from mugen.core.utility.rgql.orderby_parser import (
    _split_commas_top_level,
    parse_orderby,
)


class TestMugenRgqlOrderByParser(unittest.TestCase):
    """Covers top-level comma splitting and orderby direction parsing."""

    def test_split_commas_top_level_ignores_nested_and_quoted_commas(self) -> None:
        text = "a, fn(b,c), {'k':[1,2]}, 'x,y', t"
        parts = _split_commas_top_level(text)
        self.assertEqual(parts, ["a", "fn(b,c)", "{'k':[1,2]}", "'x,y'", "t"])

    def test_split_commas_top_level_handles_escaped_single_quote(self) -> None:
        parts = _split_commas_top_level("name,'it''s,fine',age")
        self.assertEqual(parts, ["name", "'it''s,fine'", "age"])

    def test_split_commas_top_level_drops_empty_segments(self) -> None:
        self.assertEqual(_split_commas_top_level("a,,b"), ["a", "b"])
        self.assertEqual(_split_commas_top_level("a,"), ["a"])
        self.assertEqual(_split_commas_top_level("a,   "), ["a"])

    def test_parse_orderby_applies_default_and_explicit_directions(self) -> None:
        with patch(
            "mugen.core.utility.rgql.orderby_parser.parse_rgql_expr",
            side_effect=lambda expr: Identifier(name=expr),
        ) as parse_expr:
            items = parse_orderby("Name desc, Age asc, Score")

        self.assertEqual([item.direction for item in items], ["desc", "asc", "asc"])
        self.assertEqual([item.expr.name for item in items], ["Name", "Age", "Score"])
        self.assertEqual(parse_expr.call_count, 3)

    def test_parse_orderby_raises_when_segment_lacks_expression(self) -> None:
        with self.assertRaises(ParseError):
            parse_orderby("desc")
