"""Minimal parser for the simple search expression language used by RGQL.

The search language is intentionally small: it supports free-text terms,
quoted phrases, parentheses, and the logical connectives ``and``, ``or``
and ``not``.  Whitespace between terms is treated as an implicit ``and``.

The result is a tree of :class:`SearchExpr` nodes that higher layers can
map to concrete full-text or field-specific search semantics.
"""

from dataclasses import dataclass
from typing import List


class SearchParseError(Exception):
    """Error raised when a search expression cannot be tokenized or parsed.

    This is separate from the general expression :class:`ParseError`
    because search expressions have their own tiny grammar and error
    reporting needs.
    """


# ----------------------------------------------------------------------
# AST
# ----------------------------------------------------------------------


class SearchExpr:  # pylint: disable=too-few-public-methods
    """Base class for all nodes in the search expression AST.

    Concrete subclasses model simple terms, negation, and binary
    combinations.  The semantic layer decides how to interpret this
    abstract tree (which fields are searched, stemming rules, etc.).
    """


@dataclass
class SearchTerm(SearchExpr):
    """Leaf node representing an individual search term.

    Attributes
    ----------
    text:
        The term text as it appeared in the query (case preserved).
    is_phrase:
        ``True`` if the term came from a quoted phrase (``"..."``)
        rather than a bare word.  Callers can use this to distinguish
        exact-phrase matches from token-based matches.
    """

    text: str  # original text
    is_phrase: bool  # True if quoted phrase


@dataclass
class SearchNot(SearchExpr):
    """Logical negation of a search expression.

    Models the ``not`` operator in the search grammar.  ``operand`` is
    another :class:`SearchExpr`.
    """

    operand: SearchExpr


@dataclass
class SearchBinary(SearchExpr):
    """Binary combination of two search expressions using ``and`` or ``or``.

    Attributes
    ----------
    op:
        Either ``"and"`` or ``"or"``.
    left, right:
        The left and right operands.
    """

    op: str  # "and" or "or"
    left: SearchExpr
    right: SearchExpr


# ----------------------------------------------------------------------
# Lexer
# ----------------------------------------------------------------------


@dataclass
class _SearchToken:
    kind: str  # "WORD", "PHRASE", "LPAREN", "RPAREN", "AND", "OR", "NOT", "EOF"
    text: str


class _SearchLexer:  # pylint: disable=too-few-public-methods
    """Very small lexer for the RGQL search language.

    It tokenizes the subset of syntax used by the ``$search``-style
    option:

        searchExpr = searchTerm ( (AND | OR) searchTerm )*
        searchTerm = [NOT] ( WORD | "PHRASE" | "(" searchExpr ")" )

    Whitespace between terms is treated as implicit AND by the parser.
    """

    def __init__(self, text: str):
        self.text = text
        self.length = len(text)
        self.pos = 0

    def _peek(self) -> str:
        if self.pos >= self.length:
            return ""
        return self.text[self.pos]

    def _advance(self) -> str:
        ch = self._peek()
        self.pos += 1
        return ch

    def _skip_ws(self) -> None:
        while self._peek().isspace():
            self.pos += 1

    def next_token(self) -> _SearchToken:
        """Return the next token from the search string.

        The lexer recognizes:

          * ``WORD`` - unquoted term without spaces
          * ``PHRASE`` - a ``"quoted phrase"``
          * ``LPAREN`` / ``RPAREN`` - parentheses
          * ``AND`` / ``OR`` / ``NOT`` - logical operators (case-insensitive)
          * ``EOF`` - end-of-input marker

        Any invalid character or unterminated quoted phrase results in a
        :class:`SearchParseError`.
        """
        self._skip_ws()
        ch = self._peek()
        if not ch:
            return _SearchToken("EOF", "")

        if ch == "(":
            self._advance()
            return _SearchToken("LPAREN", "(")
        if ch == ")":
            self._advance()
            return _SearchToken("RPAREN", ")")

        # Phrase: "..."
        if ch == '"':
            return self._read_phrase()

        # Word or keyword
        return self._read_word()

    def _read_phrase(self) -> _SearchToken:
        if self._advance() != '"':
            raise SearchParseError("Expected opening quote for phrase")
        buf: List[str] = []
        while True:
            ch = self._peek()
            if not ch:
                raise SearchParseError("Unterminated phrase in $search")
            self._advance()
            if ch == '"':
                break
            buf.append(ch)
        text = "".join(buf)
        return _SearchToken("PHRASE", text)

    def _read_word(self) -> _SearchToken:
        start = self.pos
        while True:
            ch = self._peek()
            if not ch or ch.isspace() or ch in '()"':
                break
            self.pos += 1
        word = self.text[start : self.pos]
        wl = word.lower()
        if wl == "and":
            return _SearchToken("AND", word)
        if wl == "or":
            return _SearchToken("OR", word)
        if wl == "not":
            return _SearchToken("NOT", word)
        return _SearchToken("WORD", word)


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------


class _SearchParser:  # pylint: disable=too-few-public-methods
    def __init__(self, text: str):
        self.lexer = _SearchLexer(text)
        self.current = self.lexer.next_token()

    def _advance(self) -> None:
        self.current = self.lexer.next_token()

    def _eat(self, kind: str) -> str:
        if self.current.kind != kind:
            raise SearchParseError(
                f"Expected {kind}, got {self.current.kind} ({self.current.text!r})"
            )
        text = self.current.text
        self._advance()
        return text

    def parse(self) -> SearchExpr:
        """Entry point for the recursive-descent search parser.

        Consumes the entire token stream produced by
        :class:`_SearchLexer`.  If extra tokens remain after a valid
        expression has been parsed, a :class:`SearchParseError` is raised.
        """
        expr = self._parse_or()
        if self.current.kind != "EOF":
            raise SearchParseError(f"Unexpected token {self.current}")
        return expr

    def _parse_or(self) -> SearchExpr:
        expr = self._parse_and()
        while self.current.kind == "OR":
            self._advance()
            right = self._parse_and()
            expr = SearchBinary("or", expr, right)
        return expr

    def _parse_and(self) -> SearchExpr:
        expr = self._parse_unary()
        while self.current.kind in ("AND", "WORD", "PHRASE", "LPAREN", "NOT"):
            # Implicit AND if the next token starts a term
            if self.current.kind == "AND":
                self._advance()
            right = self._parse_unary()
            expr = SearchBinary("and", expr, right)
        return expr

    def _parse_unary(self) -> SearchExpr:
        if self.current.kind == "NOT":
            self._advance()
            operand = self._parse_unary()
            return SearchNot(operand)
        return self._parse_primary()

    def _parse_primary(self) -> SearchExpr:
        tok = self.current
        if tok.kind == "WORD":
            self._advance()
            return SearchTerm(text=tok.text, is_phrase=False)
        if tok.kind == "PHRASE":
            self._advance()
            return SearchTerm(text=tok.text, is_phrase=True)
        if tok.kind == "LPAREN":
            self._advance()
            expr = self._parse_or()
            self._eat("RPAREN")
            return expr
        raise SearchParseError(f"Unexpected token in $search: {tok}")


def parse_rgql_search(text: str) -> SearchExpr:
    """Parse a search string into a :class:`SearchExpr` tree.

    This convenience wrapper runs the text through :class:`_SearchLexer`
    and :class:`_SearchParser` and returns the resulting abstract syntax
    tree.  It is intended for values coming from the ``$search`` query
    option but can also be used directly.

    Any lexical or syntactic error results in a :class:`SearchParseError`.
    """
    parser = _SearchParser(text)
    return parser.parse()
