"""Token kinds and lexer for the RGQL expression language.

The lexer converts a raw query string into a flat stream of :class:`Token`
objects.  Parsers in this package consume that stream to build AST nodes.

Only a small, well-defined subset of characters has syntactic meaning:
everything else is turned into identifiers, numeric literals, string
literals, or JSON literals.
"""

__all__ = ["TokenKind", "Token", "RGQLLexer"]

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, List
import decimal
import json


class TokenKind(Enum):
    """Enumeration of all token categories produced by :class:`RGQLLexer`.

    The categories fall into a few groups:

      * literals and identifiers (``IDENT``, numeric kinds, ``STRING``,
        parameter aliases, booleans, ``NULL``, ``JSON_LITERAL``)
      * punctuation (parentheses, comma, dot, slash, colon)
      * logical and comparison operators (``AND``, ``OR``, ``EQ`` etc.)
      * arithmetic operators (``ADD``, ``SUB``, ``MUL``, ``DIV``, ``MOD``)
      * lambda and type-related keywords (``ANY``, ``ALL``, ``CAST``,
        ``ISOF``)
      * ``EOF`` - end of input sentinel used by the parsers

    The exact textual spellings are handled by the lexer; downstream code
    should rely on these symbolic names.
    """

    # Literals and identifiers
    IDENT = auto()
    PARAM_ALIAS = auto()  # @p1

    STRING = auto()
    INT = auto()
    FLOAT = auto()
    DECIMAL = auto()

    TRUE = auto()
    FALSE = auto()
    NULL = auto()

    # JSON literal (complex / collection literal via arrayOrObject)
    JSON_LITERAL = auto()

    # Punctuation
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    DOT = auto()
    SLASH = auto()
    COLON = auto()

    # Operators / keywords
    AND = auto()
    OR = auto()
    NOT = auto()

    EQ = auto()
    NE = auto()
    GT = auto()
    GE = auto()
    LT = auto()
    LE = auto()
    HAS = auto()
    IN = auto()

    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()

    ANY = auto()
    ALL = auto()

    CAST = auto()
    ISOF = auto()

    EOF = auto()


@dataclass
class Token:
    """Single lexical token produced by :class:`RGQLLexer`.

    Attributes
    ----------
    kind:
        The :class:`TokenKind` describing the token category.
    text:
        The exact substring from the original input.
    value:
        Parsed value for literals (e.g. ``int``/``decimal.Decimal`` for
        numbers, ``str`` for strings, ``True``/``False``/``None`` for
        booleans and null).  For non-literal tokens this is usually
        ``None`` or a simple helper value such as the identifier text.
    position:
        Zero-based character offset in the original input where the token
        begins.  Useful for error reporting.
    """

    kind: TokenKind
    text: str
    value: Any
    position: int

    def __repr__(self) -> str:
        return (
            f"Token({self.kind}, {self.text!r}, value={self.value!r},"
            f" pos={self.position})"
        )


_KEYWORDS = {
    "and": TokenKind.AND,
    "or": TokenKind.OR,
    "not": TokenKind.NOT,
    "true": TokenKind.TRUE,
    "false": TokenKind.FALSE,
    "null": TokenKind.NULL,
    "eq": TokenKind.EQ,
    "ne": TokenKind.NE,
    "gt": TokenKind.GT,
    "ge": TokenKind.GE,
    "lt": TokenKind.LT,
    "le": TokenKind.LE,
    "has": TokenKind.HAS,
    "in": TokenKind.IN,
    "add": TokenKind.ADD,
    "sub": TokenKind.SUB,
    "mul": TokenKind.MUL,
    "div": TokenKind.DIV,
    "mod": TokenKind.MOD,
    "any": TokenKind.ANY,
    "all": TokenKind.ALL,
    "cast": TokenKind.CAST,
    "isof": TokenKind.ISOF,
}


class RGQLLexer:  # pylint: disable=too-few-public-methods
    """Lexer for the core RGQL expression language.

    Produces tokens for:

      * identifiers and parameter aliases (``@p1``)
      * numeric and string literals (using single-quote escaping)
      * booleans and ``null``
      * JSON literals (``{...}`` / ``[...]``) as a single ``JSON_LITERAL``
      * keywords and operators
      * punctuation used in expressions and resource paths

    The exact mapping from characters to :class:`TokenKind` values is
    defined by the internal ``_next_token`` method.
    """

    def __init__(self, text: str):
        self.text = text
        self.length = len(text)
        self.pos = 0

    # Core API ----------------------------------------------------------

    def tokenize(self) -> List[Token]:
        """Tokenize the entire input string.

        The method repeatedly calls the internal ``_next_token`` helper
        until an ``EOF`` token is produced, then returns the full list of
        tokens including that sentinel.  Whitespace is skipped; no
        whitespace tokens are emitted.

        Raises
        ------
        ValueError
            If an unexpected character is encountered or an internal
            safety check detects that advancing through the input has
            stalled.
        """
        tokens: List[Token] = []
        while True:
            tok = self._next_token()
            tokens.append(tok)
            if tok.kind == TokenKind.EOF:
                break
            # safety: avoid infinite loops
            if self.pos > self.length:
                raise ValueError("Lexer overran input")
        return tokens

    # Internal helpers --------------------------------------------------

    def _peek_char(self) -> str:
        if self.pos >= self.length:
            return ""
        return self.text[self.pos]

    def _advance_char(self) -> str:
        ch = self._peek_char()
        self.pos += 1
        return ch

    def _skip_ws(self) -> None:
        while self._peek_char().isspace():
            self.pos += 1

    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches
    def _next_token(self) -> Token:
        self._skip_ws()
        start = self.pos
        ch = self._peek_char()

        if not ch:
            return Token(TokenKind.EOF, "", None, self.pos)

        # Parameter alias: @p1
        if ch == "@":
            self._advance_char()
            ident = self._read_identifier()
            if not ident:
                raise ValueError(f"Invalid parameter alias at position {start}")
            text = "@" + ident
            return Token(TokenKind.PARAM_ALIAS, text, text, start)

        # JSON complex/collection literal: { ... } or [ ... ]
        if ch in "{[":
            return self._read_json_literal()

        # Identifiers and keywords
        if ch.isalpha() or ch == "_":
            ident = self._read_identifier()
            kind = _KEYWORDS.get(ident.lower(), TokenKind.IDENT)
            if kind == TokenKind.TRUE:
                value: Any = True
            elif kind == TokenKind.FALSE:
                value = False
            elif kind == TokenKind.NULL:
                value = None
            else:
                value = ident
            return Token(kind, ident, value, start)

        # Numbers
        if ch.isdigit():
            return self._read_number()

        # String literal: '...'
        if ch == "'":
            return self._read_string()

        # Single-character tokens
        if ch == "(":
            self._advance_char()
            return Token(TokenKind.LPAREN, "(", None, start)
        if ch == ")":
            self._advance_char()
            return Token(TokenKind.RPAREN, ")", None, start)
        if ch == ",":
            self._advance_char()
            return Token(TokenKind.COMMA, ",", None, start)
        if ch == ".":
            self._advance_char()
            return Token(TokenKind.DOT, ".", None, start)
        if ch == "/":
            self._advance_char()
            return Token(TokenKind.SLASH, "/", None, start)
        if ch == ":":
            self._advance_char()
            return Token(TokenKind.COLON, ":", None, start)

        # Operators that are single characters in the URL language
        if ch == "+":
            self._advance_char()
            return Token(TokenKind.ADD, "+", None, start)
        if ch == "-":
            self._advance_char()
            return Token(TokenKind.SUB, "-", None, start)
        if ch == "*":
            self._advance_char()
            return Token(TokenKind.MUL, "*", None, start)
        if ch == "%":
            self._advance_char()
            return Token(TokenKind.MOD, "%", None, start)

        raise ValueError(f"Unexpected character {ch!r} at position {start}")

    # Identifier / number / string readers ------------------------------

    def _read_identifier(self) -> str:
        start = self.pos
        while True:
            ch = self._peek_char()
            if not (ch.isalnum() or ch == "_" or ch == "."):
                break
            self.pos += 1
        return self.text[start : self.pos]

    def _read_number(self) -> Token:
        start = self.pos
        has_dot = False
        has_exp = False

        while True:
            ch = self._peek_char()
            if ch.isdigit():
                self.pos += 1
                continue
            if ch == "." and not has_dot and not has_exp:
                has_dot = True
                self.pos += 1
                continue
            if ch and ch in "eE" and not has_exp:
                has_exp = True
                self.pos += 1
                next_ch = self._peek_char()
                if next_ch and next_ch in "+-":
                    self.pos += 1
                continue
            break

        suffix = self._peek_char()
        raw = self.text[start : self.pos]
        kind = None
        value: Any = None

        if suffix and suffix in "Mm":
            self.pos += 1
            raw_with_suffix = self.text[start : self.pos]
            kind = TokenKind.DECIMAL
            value = decimal.Decimal(raw)
            return Token(kind, raw_with_suffix, value, start)

        if suffix and suffix in "Ll":
            self.pos += 1
            raw_with_suffix = self.text[start : self.pos]
            kind = TokenKind.INT
            value = int(raw)
            return Token(kind, raw_with_suffix, value, start)

        if has_dot or has_exp:
            kind = TokenKind.FLOAT
            value = float(raw)
        else:
            kind = TokenKind.INT
            value = int(raw)

        text = self.text[start : self.pos]
        return Token(kind, text, value, start)

    def _read_string(self) -> Token:
        start = self.pos
        if self._advance_char() != "'":
            raise ValueError(f"Expected string quote at position {start}")
        buf: List[str] = []

        while True:
            ch = self._peek_char()
            if not ch:
                raise ValueError(f"Unterminated string literal starting at {start}")

            self.pos += 1
            if ch == "'":
                next_ch = self._peek_char()
                if next_ch == "'":
                    buf.append("'")
                    self.pos += 1
                    continue
                break
            buf.append(ch)

        value = "".join(buf)
        text = self.text[start : self.pos]
        return Token(TokenKind.STRING, text, value, start)

    # JSON literal reader -----------------------------------------------

    def _read_json_literal(self) -> Token:
        """
        Read a JSON object/array starting at '{' or '[' and return a JSON_LITERAL.

        We scan balanced braces/brackets, respecting JSON string rules and escapes,
        then parse the substring with json.loads.
        """
        start = self.pos
        first = self._advance_char()
        if first == "{":
            stack = ["}"]
        else:
            stack = ["]"]

        in_string = False
        escape = False

        while stack:
            ch = self._peek_char()
            if not ch:
                raise ValueError(f"Unterminated JSON literal starting at {start}")
            self.pos += 1

            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                stack.append("}")
                continue
            if ch == "[":
                stack.append("]")
                continue
            if ch in "}]":
                if not stack or ch != stack[-1]:
                    raise ValueError(
                        f"Mismatched brace/bracket {ch!r} in JSON literal at position"
                        f" {self.pos}"
                    )
                stack.pop()
                continue

        text = self.text[start : self.pos]
        try:
            value = json.loads(text)
        except Exception as exc:
            raise ValueError(f"Invalid JSON literal {text!r}: {exc}") from exc

        return Token(TokenKind.JSON_LITERAL, text, value, start)
