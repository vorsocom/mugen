"""Unit tests for RGQL expression parser."""

import datetime
import decimal
import math
import uuid
import unittest

from mugen.core.utility.rgql.lexer import RGQLLexer, Token, TokenKind
from mugen.core.utility.rgql.ast import (
    BinaryOp,
    CastExpr,
    EnumLiteral,
    Expr,
    FunctionCall,
    Identifier,
    IsOfExpr,
    LambdaCall,
    Literal,
    MemberAccess,
    SpatialLiteral,
    TypeRef,
    UnaryOp,
)
from mugen.core.utility.rgql.expr_parser import (
    ExprParser,
    ParseError,
    _parse_date,
    _parse_datetimeoffset,
    _parse_duration,
    _parse_spatial_literal_payload,
    _parse_time_of_day,
    parse_rgql_expr,
)


class TestMugenRgqlExprParser(unittest.TestCase):
    """Covers literal parsing, grammar rules, and error paths."""

    def test_duration_helper_parses_sign_and_fraction(self) -> None:
        self.assertEqual(_parse_duration("P2DT3H4M"), datetime.timedelta(days=2, hours=3, minutes=4))
        self.assertEqual(_parse_duration("-PT1.5S"), datetime.timedelta(seconds=-1, microseconds=-500000))
        with self.assertRaises(ValueError):
            _parse_duration("P")

    def test_time_date_and_datetime_helpers(self) -> None:
        self.assertEqual(_parse_time_of_day("10:20"), datetime.time(10, 20))
        self.assertEqual(_parse_time_of_day("10:20:30.5"), datetime.time(10, 20, 30, 500000))
        self.assertEqual(_parse_time_of_day("10:20:30"), datetime.time(10, 20, 30))
        with self.assertRaises(ValueError):
            _parse_time_of_day("10")
        self.assertEqual(_parse_date("2026-02-14"), datetime.date(2026, 2, 14))
        self.assertEqual(
            _parse_datetimeoffset("2026-02-14T10:20:30Z"),
            datetime.datetime(2026, 2, 14, 10, 20, 30, tzinfo=datetime.timezone.utc),
        )
        self.assertEqual(
            _parse_datetimeoffset("2026-02-14T10:20:30+01:00"),
            datetime.datetime(
                2026,
                2,
                14,
                10,
                20,
                30,
                tzinfo=datetime.timezone(datetime.timedelta(hours=1)),
            ),
        )

    def test_spatial_literal_helper(self) -> None:
        self.assertEqual(
            _parse_spatial_literal_payload(True, "SRID=4326;POINT(10 20)"),
            SpatialLiteral(is_geography=True, srid=4326, wkt="POINT(10 20)"),
        )
        self.assertEqual(
            _parse_spatial_literal_payload(False, "POINT(10 20)"),
            SpatialLiteral(is_geography=False, srid=None, wkt="POINT(10 20)"),
        )
        with self.assertRaises(ValueError):
            _parse_spatial_literal_payload(True, "SRID=4326")

    def test_parse_basic_literals_and_json(self) -> None:
        self.assertEqual(parse_rgql_expr("123"), Literal(123))
        self.assertEqual(parse_rgql_expr("12.5"), Literal(12.5))
        self.assertEqual(parse_rgql_expr("12.5m"), Literal(decimal.Decimal("12.5")))
        self.assertEqual(parse_rgql_expr("'hello'"), Literal("hello"))
        self.assertEqual(parse_rgql_expr("true"), Literal(True))
        self.assertEqual(parse_rgql_expr("false"), Literal(False))
        self.assertEqual(parse_rgql_expr("null"), Literal(None))
        self.assertEqual(parse_rgql_expr("{\"a\":1,\"b\":[2]}"), Literal({"a": 1, "b": [2]}))

    def test_parse_special_literals(self) -> None:
        nan_expr = parse_rgql_expr("NaN")
        inf_expr = parse_rgql_expr("INF")
        self.assertIsInstance(nan_expr, Literal)
        self.assertTrue(math.isnan(nan_expr.value))
        self.assertEqual(inf_expr, Literal(float("inf")))

        guid_val = uuid.uuid4()
        self.assertEqual(parse_rgql_expr(f"guid'{guid_val}'"), Literal(guid_val))
        self.assertEqual(parse_rgql_expr("binary'0A0B'"), Literal(bytes.fromhex("0A0B")))
        self.assertEqual(parse_rgql_expr("x'0A0B'"), Literal(bytes.fromhex("0A0B")))
        self.assertEqual(parse_rgql_expr("date'2026-02-14'"), Literal(datetime.date(2026, 2, 14)))
        self.assertEqual(
            parse_rgql_expr("datetimeoffset'2026-02-14T10:20:30Z'"),
            Literal(datetime.datetime(2026, 2, 14, 10, 20, 30, tzinfo=datetime.timezone.utc)),
        )
        self.assertEqual(parse_rgql_expr("duration'PT30S'"), Literal(datetime.timedelta(seconds=30)))
        self.assertEqual(parse_rgql_expr("timeofday'10:20:30.25'"), Literal(datetime.time(10, 20, 30, 250000)))
        self.assertEqual(
            parse_rgql_expr("geography'SRID=4326;POINT(10 20)'"),
            SpatialLiteral(is_geography=True, srid=4326, wkt="POINT(10 20)"),
        )
        self.assertEqual(
            parse_rgql_expr("geometry'POINT(10 20)'"),
            SpatialLiteral(is_geography=False, srid=None, wkt="POINT(10 20)"),
        )
        self.assertEqual(parse_rgql_expr("NS.Color'Red,Blue'"), EnumLiteral("NS.Color", ["Red", "Blue"]))
        self.assertEqual(parse_rgql_expr("P1DT2H"), Literal(datetime.timedelta(days=1, hours=2)))

    def test_parse_operators_precedence_and_unary(self) -> None:
        expr = parse_rgql_expr("1 add 2 mul 3")
        self.assertEqual(expr, BinaryOp("add", Literal(1), BinaryOp("mul", Literal(2), Literal(3))))
        self.assertEqual(parse_rgql_expr("(1 add 2)"), BinaryOp("add", Literal(1), Literal(2)))

        expr = parse_rgql_expr("not a and b or c")
        self.assertEqual(
            expr,
            BinaryOp(
                "or",
                BinaryOp("and", UnaryOp("not", Identifier("a")), Identifier("b")),
                Identifier("c"),
            ),
        )

        expr = parse_rgql_expr("-1")
        self.assertEqual(expr, UnaryOp("-", Literal(1)))

        cmp_expr = parse_rgql_expr("a eq b ne c gt d ge e lt f le g has h")
        self.assertIsInstance(cmp_expr, BinaryOp)
        self.assertEqual(cmp_expr.op, "has")

    def test_parse_in_operator_forms(self) -> None:
        expr = parse_rgql_expr("Status in ('Supported','Obsolete')")
        self.assertEqual(
            expr,
            BinaryOp("in", Identifier("Status"), Literal(["Supported", "Obsolete"])),
        )
        self.assertEqual(
            parse_rgql_expr("Status in ()"),
            BinaryOp("in", Identifier("Status"), Literal([])),
        )
        self.assertEqual(
            parse_rgql_expr("Status in OtherStatus"),
            BinaryOp("in", Identifier("Status"), Identifier("OtherStatus")),
        )
        with self.assertRaises(ParseError):
            parse_rgql_expr("Status in (OtherStatus)")

    def test_parse_identifier_member_function_and_param_alias(self) -> None:
        self.assertEqual(parse_rgql_expr("@p1"), Identifier("@p1"))
        self.assertEqual(
            parse_rgql_expr("a.b/c"),
            MemberAccess(Identifier("a.b"), "c"),
        )
        self.assertEqual(
            parse_rgql_expr("length(Name)"),
            FunctionCall("length", [Identifier("Name")]),
        )
        self.assertEqual(
            parse_rgql_expr("fn(a, 1, 'x').prop"),
            MemberAccess(
                FunctionCall("fn", [Identifier("a"), Literal(1), Literal("x")]),
                "prop",
            ),
        )
        self.assertEqual(parse_rgql_expr("fn()"), FunctionCall("fn", []))

    def test_parse_lambdas(self) -> None:
        self.assertEqual(
            parse_rgql_expr("Orders/any()"),
            LambdaCall(kind="any", source=Identifier("Orders"), var=None, predicate=None),
        )
        self.assertEqual(
            parse_rgql_expr("Orders/all(o:o/Price gt 5)"),
            LambdaCall(
                kind="all",
                source=Identifier("Orders"),
                var="o",
                predicate=BinaryOp(
                    "gt",
                    MemberAccess(Identifier("o"), "Price"),
                    Literal(5),
                ),
            ),
        )

    def test_parse_type_functions(self) -> None:
        self.assertEqual(
            parse_rgql_expr("cast(NS.Customer)"),
            CastExpr(
                source=None,
                type_ref=TypeRef(
                    is_collection=False,
                    namespace="NS",
                    name="Customer",
                    full_name="NS.Customer",
                ),
            ),
        )
        self.assertEqual(
            parse_rgql_expr("isof(Address, NS.Address)"),
            IsOfExpr(
                source=Identifier("Address"),
                type_ref=TypeRef(
                    is_collection=False,
                    namespace="NS",
                    name="Address",
                    full_name="NS.Address",
                ),
            ),
        )
        self.assertEqual(
            parse_rgql_expr("cast(Order, Collection(NS.Item))"),
            CastExpr(
                source=Identifier("Order"),
                type_ref=TypeRef(
                    is_collection=True,
                    namespace="NS",
                    name="Item",
                    full_name="Collection(NS.Item)",
                ),
            ),
        )

    def test_parse_errors(self) -> None:
        with self.assertRaises(ParseError):
            parse_rgql_expr("cast()")
        with self.assertRaises(ParseError):
            parse_rgql_expr("cast(1)")
        with self.assertRaises(ParseError):
            parse_rgql_expr("/")
        with self.assertRaises(ParseError):
            parse_rgql_expr("1 2")
        with self.assertRaises(ParseError):
            parse_rgql_expr("guid'not-a-guid'")
        with self.assertRaises(ParseError):
            parse_rgql_expr("binary'ABC'")
        with self.assertRaises(ParseError):
            parse_rgql_expr("geography'SRID=4326'")

    def test_internal_helpers_for_error_and_dot_token_branches(self) -> None:
        tokens = RGQLLexer("1").tokenize()
        parser = ExprParser(tokens)
        parser.pos = len(tokens) + 10
        self.assertEqual(parser._peek().kind, TokenKind.EOF)  # pylint: disable=protected-access
        self.assertEqual(parser._peek_offset(10).kind, TokenKind.EOF)  # pylint: disable=protected-access
        with self.assertRaises(ParseError):
            parser._expect(TokenKind.IDENT)  # pylint: disable=protected-access
        self.assertIsNone(parser._try_parse_special_literal())  # pylint: disable=protected-access

        enum_tokens = [
            Token(TokenKind.IDENT, "NS", "NS", 0),
            Token(TokenKind.DOT, ".", None, 2),
            Token(TokenKind.IDENT, "Color", "Color", 3),
            Token(TokenKind.STRING, "'Red,Blue'", "Red,Blue", 8),
            Token(TokenKind.EOF, "", None, 18),
        ]
        enum_parser = ExprParser(enum_tokens)
        self.assertEqual(
            enum_parser._try_parse_enum_literal_chain(),  # pylint: disable=protected-access
            EnumLiteral("NS.Color", ["Red", "Blue"]),
        )
        non_enum_parser = ExprParser(
            [
                Token(TokenKind.STRING, "'x'", "x", 0),
                Token(TokenKind.EOF, "", None, 3),
            ]
        )
        self.assertIsNone(
            non_enum_parser._try_parse_enum_literal_chain()  # pylint: disable=protected-access
        )

        type_tokens = [
            Token(TokenKind.IDENT, "NS", "NS", 0),
            Token(TokenKind.DOT, ".", None, 2),
            Token(TokenKind.IDENT, "Address", "Address", 3),
            Token(TokenKind.EOF, "", None, 10),
        ]
        type_parser = ExprParser(type_tokens)
        self.assertEqual(
            type_parser._parse_type_name(),  # pylint: disable=protected-access
            TypeRef(False, "NS", "Address", "NS.Address"),
        )

        member_type = type_parser._expr_to_type_name(  # pylint: disable=protected-access
            MemberAccess(MemberAccess(Identifier("NS"), "Address"), "Inner")
        )
        self.assertEqual(member_type, TypeRef(False, "NS.Address", "Inner", "NS.Address.Inner"))

        class _Unknown(Expr):
            pass

        with self.assertRaises(ParseError):
            type_parser._expr_to_type_name(_Unknown())  # pylint: disable=protected-access
        with self.assertRaises(ParseError):
            type_parser._expr_to_type_name(  # pylint: disable=protected-access
                MemberAccess(Literal(1), "x")
            )
