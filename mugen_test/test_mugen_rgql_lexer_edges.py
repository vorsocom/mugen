"""Edge-branch unit tests for mugen.core.utility.rgql.lexer.RGQLLexer."""

import unittest
from unittest.mock import Mock

from mugen.core.utility.rgql.lexer import RGQLLexer, Token, TokenKind


class TestMugenRGQLLexerEdges(unittest.TestCase):
    """Covers low-frequency lexer branches and error paths."""

    def test_tokenize_raises_on_internal_position_overrun(self) -> None:
        lexer = RGQLLexer("x")
        lexer._next_token = Mock(  # pylint: disable=protected-access
            return_value=Token(TokenKind.IDENT, "x", "x", 0)
        )
        lexer.pos = lexer.length + 1

        with self.assertRaises(ValueError):
            lexer.tokenize()

    def test_rejects_invalid_parameter_alias(self) -> None:
        with self.assertRaises(ValueError):
            RGQLLexer("@").tokenize()

    def test_single_character_operator_tokens_and_unexpected_character(self) -> None:
        add_tokens = RGQLLexer("+").tokenize()
        self.assertEqual(add_tokens[0].kind, TokenKind.ADD)
        self.assertEqual(add_tokens[0].text, "+")

        mul_tokens = RGQLLexer("*").tokenize()
        self.assertEqual(mul_tokens[0].kind, TokenKind.MUL)
        self.assertEqual(mul_tokens[0].text, "*")

        mod_tokens = RGQLLexer("%").tokenize()
        self.assertEqual(mod_tokens[0].kind, TokenKind.MOD)
        self.assertEqual(mod_tokens[0].text, "%")

        with self.assertRaises(ValueError):
            RGQLLexer("?").tokenize()

    def test_number_reader_parses_exponent_sign_and_long_suffix(self) -> None:
        exp_tokens = RGQLLexer("1e-2").tokenize()
        self.assertEqual(exp_tokens[0].kind, TokenKind.FLOAT)
        self.assertEqual(exp_tokens[0].text, "1e-2")
        self.assertAlmostEqual(exp_tokens[0].value, 0.01)

        exp_no_sign_tokens = RGQLLexer("1e2").tokenize()
        self.assertEqual(exp_no_sign_tokens[0].kind, TokenKind.FLOAT)
        self.assertEqual(exp_no_sign_tokens[0].text, "1e2")
        self.assertAlmostEqual(exp_no_sign_tokens[0].value, 100.0)

        int_tokens = RGQLLexer("42L").tokenize()
        self.assertEqual(int_tokens[0].kind, TokenKind.INT)
        self.assertEqual(int_tokens[0].text, "42L")
        self.assertEqual(int_tokens[0].value, 42)

    def test_string_reader_handles_escaped_quote_and_unterminated_string(self) -> None:
        tokens = RGQLLexer("'a''b'").tokenize()
        self.assertEqual(tokens[0].kind, TokenKind.STRING)
        self.assertEqual(tokens[0].value, "a'b")

        with self.assertRaises(ValueError):
            RGQLLexer("'abc").tokenize()

    def test_string_reader_requires_opening_quote(self) -> None:
        lexer = RGQLLexer("abc")
        with self.assertRaisesRegex(ValueError, "Expected string quote"):
            lexer._read_string()  # pylint: disable=protected-access

    def test_json_reader_handles_escape_nested_mismatch_and_invalid_payload(self) -> None:
        escaped = RGQLLexer('{"k":"a\\\"b"}').tokenize()
        self.assertEqual(escaped[0].kind, TokenKind.JSON_LITERAL)
        self.assertEqual(escaped[0].value, {"k": 'a"b'})

        nested = RGQLLexer('[{"a":1}]').tokenize()
        self.assertEqual(nested[0].kind, TokenKind.JSON_LITERAL)
        self.assertEqual(nested[0].value, [{"a": 1}])

        with self.assertRaises(ValueError):
            RGQLLexer("{").tokenize()

        with self.assertRaises(ValueError):
            RGQLLexer("{]").tokenize()

        with self.assertRaises(ValueError):
            RGQLLexer("{foo:1}").tokenize()
