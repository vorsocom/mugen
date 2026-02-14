"""Unit tests for RGQL search parsing."""

import unittest

from mugen.core.utility.rgql.search_parser import (
    SearchBinary,
    SearchNot,
    SearchParseError,
    SearchTerm,
    parse_rgql_search,
)


class TestMugenRgqlSearchParser(unittest.TestCase):
    """Covers lexer and parser behavior for the search mini-language."""

    def test_parses_single_word_and_phrase(self) -> None:
        word = parse_rgql_search("alpha")
        phrase = parse_rgql_search('"hello world"')

        self.assertIsInstance(word, SearchTerm)
        self.assertEqual(word.text, "alpha")
        self.assertFalse(word.is_phrase)
        self.assertIsInstance(phrase, SearchTerm)
        self.assertEqual(phrase.text, "hello world")
        self.assertTrue(phrase.is_phrase)

    def test_parses_implicit_and_explicit_or_precedence(self) -> None:
        expr = parse_rgql_search("alpha beta or gamma")
        self.assertIsInstance(expr, SearchBinary)
        self.assertEqual(expr.op, "or")
        self.assertIsInstance(expr.left, SearchBinary)
        self.assertEqual(expr.left.op, "and")

    def test_parses_not_and_parentheses(self) -> None:
        expr = parse_rgql_search("not (alpha or beta)")
        self.assertIsInstance(expr, SearchNot)
        self.assertIsInstance(expr.operand, SearchBinary)
        self.assertEqual(expr.operand.op, "or")

    def test_parses_keywords_case_insensitively(self) -> None:
        expr = parse_rgql_search("A AnD B Or not C")
        self.assertIsInstance(expr, SearchBinary)
        self.assertEqual(expr.op, "or")

    def test_rejects_unterminated_phrase(self) -> None:
        with self.assertRaises(SearchParseError):
            parse_rgql_search('"unterminated')

    def test_rejects_mismatched_parentheses(self) -> None:
        with self.assertRaises(SearchParseError):
            parse_rgql_search("(alpha or beta")

    def test_rejects_unexpected_tokens(self) -> None:
        with self.assertRaises(SearchParseError):
            parse_rgql_search(")")
        with self.assertRaises(SearchParseError):
            parse_rgql_search("alpha )")
