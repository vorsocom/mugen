"""Expression parsing for the RGQL query language.

This module implements a hand-written recursive-descent parser on top of
:class:`RGQLLexer`. It understands the expression syntax used by RGQL
query options such as filter, ordering, search, and transformation
pipelines.

The parser is intentionally surface-syntax only: it does not know about
entity models or static types. It produces a tree of
:class:`~mugen.core.utility.rgql_parser.ast.Expr` nodes which can then
be analysed or executed by the semantic layer and evaluation engine.
"""

from typing import List, Optional
import datetime
import uuid
import decimal
import re

from mugen.core.utility.rgql.lexer import RGQLLexer, Token, TokenKind
from mugen.core.utility.rgql.ast import (
    Expr,
    Literal,
    Identifier,
    MemberAccess,
    BinaryOp,
    UnaryOp,
    FunctionCall,
    LambdaCall,
    TypeRef,
    CastExpr,
    IsOfExpr,
    EnumLiteral,
    SpatialLiteral,
)


class ParseError(Exception):
    """Raised when expression parsing fails."""


# ----------------------------------------------------------------------
# Helpers for typed primitive literals
# ----------------------------------------------------------------------

# Allow optional '+' or '-' sign (unprefixed durationValue in OData 4.01)
_DURATION_RE = re.compile(
    r"^([+-])?P"
    r"(?:(\d+)D)?"
    r"(?:T"
    r"(?:(\d+)H)?"
    r"(?:(\d+)M)?"
    r"(?:(\d+)(\.\d+)?S)?"
    r")?$"
)


def _parse_duration(text: str) -> datetime.timedelta:
    """
    Parse an ISO 8601 duration value used by Edm.Duration.

    Used both for prefixed "duration'<payload>'" and for unprefixed
    durationValue (e.g. P2DT3H4M).
    """
    m = _DURATION_RE.match(text)
    # Require at least one component (D, H, M, S); bare "P" is invalid.
    if not m or not any(m.group(i) for i in range(2, 7)):
        raise ValueError(f"Invalid duration payload: {text!r}")

    sign_group = m.group(1)
    sign = -1 if sign_group == "-" else 1
    days = int(m.group(2) or 0)
    hours = int(m.group(3) or 0)
    minutes = int(m.group(4) or 0)
    seconds = int(m.group(5) or 0)
    frac = m.group(6)

    microseconds = 0
    if frac:
        q = decimal.Decimal(frac)
        microseconds = int(
            (q * decimal.Decimal(1_000_000)).to_integral_value(
                rounding=decimal.ROUND_HALF_EVEN
            )
        )

    td = datetime.timedelta(
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        microseconds=microseconds,
    )
    return sign * td


def _parse_time_of_day(text: str) -> datetime.time:
    parts = text.split(":")
    if len(parts) < 2 or len(parts) > 3:
        raise ValueError(f"Invalid timeOfDay payload: {text!r}")

    hour = int(parts[0])
    minute = int(parts[1])
    second = 0
    microsecond = 0

    if len(parts) == 3:
        if "." in parts[2]:
            sec_str, frac = parts[2].split(".", 1)
            second = int(sec_str or 0)
            frac = "0." + frac
            q = decimal.Decimal(frac)
            microsecond = int(
                (q * decimal.Decimal(1_000_000)).to_integral_value(
                    rounding=decimal.ROUND_HALF_EVEN
                )
            )
        else:
            second = int(parts[2])

    return datetime.time(hour, minute, second, microsecond)


def _parse_date(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


def _parse_datetimeoffset(text: str) -> datetime.datetime:
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(text)


def _parse_spatial_literal_payload(is_geography: bool, payload: str) -> SpatialLiteral:
    text = payload.strip()
    srid = None

    upper = text.upper()
    if upper.startswith("SRID="):
        semi = text.find(";")
        if semi == -1:
            raise ValueError("Spatial literal with SRID must contain ';'")
        srid_str = text[5:semi]
        srid = int(srid_str)
        wkt = text[semi + 1 :].strip()
    else:
        wkt = text

    return SpatialLiteral(is_geography=is_geography, srid=srid, wkt=wkt)


# ----------------------------------------------------------------------
# Expression parser
# ----------------------------------------------------------------------


class ExprParser:  # pylint: disable=too-few-public-methods
    """Recursive-descent parser for RGQL expressions.

    The parser consumes a token stream produced by :class:`RGQLLexer` and
    builds the expression AST defined in :mod:`ast`.  It understands:

      * identifiers, member access and parameter aliases
      * primitive and JSON literals
      * arithmetic, comparison and logical operators (with the usual
        precedence rules)
      * function calls, lambda expressions, and type-related forms such
        as ``cast()`` and ``isof()``
      * enum and spatial literals, including special numeric forms such
        as ``NaN``/``INF`` and duration literals

    Only syntax is handled here; any model-aware or type-aware checks are
    performed by the semantic layer.
    """

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    # Token helpers -----------------------------------------------------

    def _peek(self) -> Token:
        if self.pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.pos]

    def _peek_offset(self, offset: int) -> Token:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def _advance(self) -> Token:
        tok = self._peek()
        self.pos += 1
        return tok

    def _match(self, *kinds: TokenKind) -> Optional[Token]:
        if self._peek().kind in kinds:
            return self._advance()
        return None

    def _expect(self, kind: TokenKind) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            raise ParseError(
                f"Expected {kind.name}, got {tok.kind.name} at pos {tok.position}"
            )
        return self._advance()

    # Entry -------------------------------------------------------------

    def parse(self) -> Expr:
        """Parse the entire token stream into a single :class:`Expr`.

        The parser assumes that the full input corresponds to one RGQL
        expression. It parses according to the standard precedence rules
        implemented by the private ``_parse_*`` methods (``or``, ``and``,
        comparison operators, arithmetic, and primaries).

        If any non-EOF tokens remain after the main expression has been
        parsed, a :class:`ParseError` is raised to signal trailing junk in
        the input.

        Returns
        -------
        Expr
            The root node of the parsed expression tree.

        Raises
        ------
        ParseError
            If the token sequence does not form a valid RGQL expression or
            if extra tokens remain after parsing.
        """
        expr = self._parse_or()
        if self._peek().kind != TokenKind.EOF:
            raise ParseError(f"Unexpected token {self._peek()} at end of expression")
        return expr

    # Precedence --------------------------------------------------------

    def _parse_or(self) -> Expr:
        expr = self._parse_and()
        while self._match(TokenKind.OR):
            right = self._parse_and()
            expr = BinaryOp("or", expr, right)
        return expr

    def _parse_and(self) -> Expr:
        expr = self._parse_not()
        while self._match(TokenKind.AND):
            right = self._parse_not()
            expr = BinaryOp("and", expr, right)
        return expr

    def _parse_not(self) -> Expr:
        if self._match(TokenKind.NOT):
            operand = self._parse_not()
            return UnaryOp("not", operand)
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        expr = self._parse_additive()
        while True:
            tok = self._peek()
            if tok.kind in (
                TokenKind.EQ,
                TokenKind.NE,
                TokenKind.GT,
                TokenKind.GE,
                TokenKind.LT,
                TokenKind.LE,
                TokenKind.HAS,
                TokenKind.IN,
            ):
                self._advance()

                # Special case for OData 4.01 "in ( ... )" syntax:
                #   Status in ('Supported','Obsolete')
                # We parse the parenthesised list of *literals* and turn it into
                # a single Literal([...]) node, same shape as a JSON array.
                if tok.kind is TokenKind.IN and self._match(TokenKind.LPAREN):
                    items: List[Literal] = []

                    # Allow empty: in ()
                    if self._peek().kind != TokenKind.RPAREN:
                        while True:
                            item_expr = self._parse_primary()
                            if not isinstance(item_expr, Literal):
                                raise ParseError(
                                    "Values in 'in (...)' must be literals"
                                )
                            items.append(item_expr)
                            if not self._match(TokenKind.COMMA):
                                break

                    self._expect(TokenKind.RPAREN)
                    right: Expr = Literal([lit.value for lit in items])
                else:
                    right = self._parse_additive()
                expr = BinaryOp(tok.text.lower(), expr, right)
            else:
                break
        return expr

    def _parse_additive(self) -> Expr:
        expr = self._parse_multiplicative()
        while True:
            tok = self._peek()
            if tok.kind in (TokenKind.ADD, TokenKind.SUB):
                self._advance()
                right = self._parse_multiplicative()
                expr = BinaryOp(tok.text.lower(), expr, right)
            else:
                break
        return expr

    def _parse_multiplicative(self) -> Expr:
        expr = self._parse_unary_arith()
        while True:
            tok = self._peek()
            if tok.kind in (TokenKind.MUL, TokenKind.DIV, TokenKind.MOD):
                self._advance()
                right = self._parse_unary_arith()
                expr = BinaryOp(tok.text.lower(), expr, right)
            else:
                break
        return expr

    def _parse_unary_arith(self) -> Expr:
        tok = self._peek()
        if tok.kind == TokenKind.SUB:
            self._advance()
            operand = self._parse_unary_arith()
            return UnaryOp("-", operand)
        return self._parse_primary()

    # Primary -----------------------------------------------------------

    def _parse_primary(self) -> Expr:
        tok = self._peek()

        # JSON complex/collection literal
        if tok.kind == TokenKind.JSON_LITERAL:
            self._advance()
            return Literal(tok.value)

        # Simple literals: string, numbers, booleans, null
        if tok.kind in (
            TokenKind.STRING,
            TokenKind.INT,
            TokenKind.FLOAT,
            TokenKind.DECIMAL,
            TokenKind.TRUE,
            TokenKind.FALSE,
            TokenKind.NULL,
        ):
            self._advance()
            return Literal(tok.value)

        # Parenthesized expression
        if tok.kind == TokenKind.LPAREN:
            self._advance()
            expr = self._parse_or()
            self._expect(TokenKind.RPAREN)
            return expr

        # Type functions: isof() / cast()
        if tok.kind in (TokenKind.ISOF, TokenKind.CAST):
            return self._parse_type_function()

        # Special primitive literal forms (guid'...', date'...', enums,
        # spatial, NaN/INF, unprefixed duration)
        if tok.kind == TokenKind.IDENT:
            special = self._try_parse_special_literal()
            if special is not None:
                return special

        # Identifiers, member access, function calls, lambdas, etc.
        if tok.kind in (TokenKind.IDENT, TokenKind.PARAM_ALIAS):
            return self._parse_identifier_or_call_or_member()

        raise ParseError(f"Unexpected token {tok} in primary expression")

    # Special literal recognition --------------------------------------

    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches
    # pylint: disable=too-many-statements
    def _try_parse_special_literal(self) -> Optional[Expr]:
        tok0 = self._peek()
        if tok0.kind != TokenKind.IDENT:
            return None

        ident = tok0.text
        ident_lower = ident.lower()

        # NaN / INF
        if ident_lower == "nan":
            self._advance()
            return Literal(float("nan"))
        if ident_lower == "inf":
            self._advance()
            return Literal(float("inf"))

        # Unprefixed Edm.Duration in OData 4.01: durationValue (e.g. P2DT3H4M)
        try:
            dt = _parse_duration(ident)
        except Exception:  # pylint: disable=broad-exception-caught
            dt = None
        if dt is not None:
            self._advance()
            return Literal(dt)

        # Prefix + string forms: guid'...', date'...', timeOfDay'...', duration'...'
        next_tok = self._peek_offset(1)
        if next_tok.kind == TokenKind.STRING:
            value_text = next_tok.value  # unescaped payload
            try:
                if ident_lower == "guid":
                    py_value = uuid.UUID(value_text)
                    self._advance()
                    self._advance()
                    return Literal(py_value)

                if ident_lower in ("binary", "x"):
                    hex_str = value_text.replace(" ", "")
                    if len(hex_str) % 2 != 0:
                        raise ValueError(
                            "Binary literal must have even number of hex digits"
                        )
                    py_value = bytes.fromhex(hex_str)
                    self._advance()
                    self._advance()
                    return Literal(py_value)

                if ident_lower == "date":
                    py_value = _parse_date(value_text)
                    self._advance()
                    self._advance()
                    return Literal(py_value)

                if ident_lower == "datetimeoffset":
                    py_value = _parse_datetimeoffset(value_text)
                    self._advance()
                    self._advance()
                    return Literal(py_value)

                if ident_lower == "duration":
                    py_value = _parse_duration(value_text)
                    self._advance()
                    self._advance()
                    return Literal(py_value)

                if ident_lower == "timeofday":
                    py_value = _parse_time_of_day(value_text)
                    self._advance()
                    self._advance()
                    return Literal(py_value)

                if ident_lower in ("geography", "geometry"):
                    spatial = _parse_spatial_literal_payload(
                        is_geography=(ident_lower == "geography"),
                        payload=value_text,
                    )
                    self._advance()
                    self._advance()
                    return spatial

            except Exception as exc:
                raise ParseError(
                    f"Invalid {ident_lower} literal {next_tok.text!r}: {exc}"
                ) from exc

        # Enum literals: EnumTypeName'SomeMember,OtherMember'
        enum_lit = self._try_parse_enum_literal_chain()
        if enum_lit is not None:
            return enum_lit

        return None

    def _try_parse_enum_literal_chain(self) -> Optional[EnumLiteral]:
        start = self.pos
        tokens = self.tokens
        i = start

        if i >= len(tokens) or tokens[i].kind != TokenKind.IDENT:
            return None

        parts: List[str] = [tokens[i].text]
        i += 1

        while (
            i + 1 < len(tokens)
            and tokens[i].kind == TokenKind.DOT
            and tokens[i + 1].kind == TokenKind.IDENT
        ):
            parts.append(tokens[i + 1].text)
            i += 2

        if i >= len(tokens) or tokens[i].kind != TokenKind.STRING:
            return None

        string_tok = tokens[i]
        raw = string_tok.value or ""
        values = [v.strip() for v in raw.split(",") if v.strip()]
        type_name = ".".join(parts)

        n_to_consume = i - start + 1
        for _ in range(n_to_consume):
            self._advance()

        return EnumLiteral(type_name=type_name, values=values)

    # Type functions ----------------------------------------------------

    def _parse_type_function(self) -> Expr:
        func_tok = self._advance()
        func_name = func_tok.text.lower()

        self._expect(TokenKind.LPAREN)

        if self._peek().kind == TokenKind.RPAREN:
            raise ParseError(f"{func_name} requires at least a type name")

        first_expr = self._parse_or()

        if self._match(TokenKind.COMMA):
            source = first_expr
            type_ref = self._parse_type_name()
            self._expect(TokenKind.RPAREN)
        else:
            source = None
            type_ref = self._expr_to_type_name(first_expr)
            self._expect(TokenKind.RPAREN)

        if func_name == "cast":
            return CastExpr(source=source, type_ref=type_ref)

        return IsOfExpr(source=source, type_ref=type_ref)

    def _parse_type_name(self) -> TypeRef:
        ident_tok = self._expect(TokenKind.IDENT)

        if ident_tok.text == "Collection" and self._match(TokenKind.LPAREN):
            inner = self._parse_type_name()
            self._expect(TokenKind.RPAREN)
            full = f"Collection({inner.full_name})"
            return TypeRef(
                is_collection=True,
                namespace=inner.namespace,
                name=inner.name,
                full_name=full,
            )

        parts = ident_tok.text.split(".")
        while self._match(TokenKind.DOT):
            part_tok = self._expect(TokenKind.IDENT)
            parts.extend(part_tok.text.split("."))

        full_name = ".".join(parts)
        namespace = ".".join(parts[:-1]) if len(parts) > 1 else None
        name = parts[-1]

        return TypeRef(
            is_collection=False,
            namespace=namespace,
            name=name,
            full_name=full_name,
        )

    def _expr_to_type_name(self, expr: Expr) -> TypeRef:
        if isinstance(expr, Identifier):
            full_name = expr.name
            namespace, _, short = full_name.rpartition(".")
            namespace = namespace or None
            return TypeRef(
                is_collection=False,
                namespace=namespace,
                name=short,
                full_name=full_name,
            )

        if isinstance(expr, MemberAccess):
            parts = []
            current = expr
            while isinstance(current, MemberAccess):
                parts.append(current.member)
                current = current.base
            if isinstance(current, Identifier):
                parts.append(current.name)
                parts.reverse()
                full_name = ".".join(parts)
                namespace = ".".join(parts[:-1]) if len(parts) > 1 else None
                name = parts[-1]
                return TypeRef(
                    is_collection=False,
                    namespace=namespace,
                    name=name,
                    full_name=full_name,
                )

        raise ParseError("Expected type name (identifier or dotted name)")

    # Identifier / call / member / lambda -------------------------------

    def _parse_identifier_or_call_or_member(self) -> Expr:
        tok = self._peek()
        self._advance()
        expr: Expr = Identifier(tok.text)

        # Function call: name(...)
        if self._match(TokenKind.LPAREN):
            args: List[Expr] = []
            if not self._match(TokenKind.RPAREN):
                while True:
                    args.append(self._parse_or())
                    if self._match(TokenKind.COMMA):
                        continue
                    self._expect(TokenKind.RPAREN)
                    break
            expr = FunctionCall(name=tok.text, args=args)

        # Member access, navigation, lambdas
        while True:
            current = self._peek()

            if current.kind == TokenKind.SLASH:
                self._advance()
                next_tok = self._peek()

                if next_tok.kind in (TokenKind.ANY, TokenKind.ALL):
                    lambda_tok = self._advance()
                    kind_str = lambda_tok.text.lower()
                    self._expect(TokenKind.LPAREN)

                    if self._match(TokenKind.RPAREN):
                        expr = LambdaCall(
                            kind=kind_str,
                            source=expr,
                            var=None,
                            predicate=None,
                        )
                    else:
                        var_tok = self._expect(TokenKind.IDENT)
                        self._expect(TokenKind.COLON)
                        predicate = self._parse_or()
                        self._expect(TokenKind.RPAREN)
                        expr = LambdaCall(
                            kind=kind_str,
                            source=expr,
                            var=var_tok.text,
                            predicate=predicate,
                        )
                    continue

                name_tok = self._expect(TokenKind.IDENT)
                expr = MemberAccess(base=expr, member=name_tok.text)
                continue

            if current.kind == TokenKind.DOT:
                self._advance()
                name_tok = self._expect(TokenKind.IDENT)
                expr = MemberAccess(base=expr, member=name_tok.text)
                continue

            break

        return expr


# Convenience entry point -----------------------------------------------


def parse_rgql_expr(expr_text: str) -> Expr:
    """Parse a single RGQL expression into an :class:`Expr` syntax tree.

    This is the main convenience entry point used by other parts of the
    library whenever a free-standing expression needs to be interpreted,
    for example the value of a ``$filter`` option or a parameter alias.

    The function performs three steps:

      1. Run :class:`RGQLLexer` over ``expr_text`` to produce a token
         stream.
      2. Feed the tokens into :class:`ExprParser`.
      3. Return the root :class:`Expr` produced by
         :meth:`ExprParser.parse`.

    Parameters
    ----------
    expr_text:
        Raw textual expression (without any leading ``"$filter="`` or
        similar prefix).

    Returns
    -------
    Expr
        The root node of the parsed expression tree.

    Raises
    ------
    ParseError
        If ``expr_text`` is not a well-formed RGQL expression.
    """
    try:
        lexer = RGQLLexer(expr_text)
        tokens = lexer.tokenize()
        parser = ExprParser(tokens)
        return parser.parse()
    except ValueError as exc:
        raise ParseError(str(exc)) from exc
