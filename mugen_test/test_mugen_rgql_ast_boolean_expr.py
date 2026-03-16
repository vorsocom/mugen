"""Unit tests for RGQL AST boolean expression heuristic."""

import unittest

from mugen.core.utility.rgql.ast import (
    BinaryOp,
    FunctionCall,
    Identifier,
    IsOfExpr,
    LambdaCall,
    Literal,
    TypeRef,
    UnaryOp,
    is_boolean_expr,
)


class TestMugenRgqlAstBooleanExpr(unittest.TestCase):
    """Covers branch behavior of is_boolean_expr()."""

    def test_boolean_heuristic_for_literals_and_identifiers(self) -> None:
        self.assertTrue(is_boolean_expr(Literal(True)))
        self.assertFalse(is_boolean_expr(Literal("x")))
        self.assertTrue(is_boolean_expr(Identifier("IsActive")))

    def test_boolean_heuristic_for_unary_and_binary_ops(self) -> None:
        self.assertTrue(is_boolean_expr(UnaryOp("not", Literal(True))))
        self.assertTrue(is_boolean_expr(BinaryOp("eq", Identifier("a"), Literal(1))))
        self.assertFalse(is_boolean_expr(BinaryOp("add", Identifier("a"), Literal(1))))

    def test_boolean_heuristic_for_lambda_and_isof(self) -> None:
        type_ref = TypeRef(
            is_collection=False,
            namespace="NS",
            name="T",
            full_name="NS.T",
        )
        self.assertTrue(
            is_boolean_expr(
                LambdaCall(
                    kind="any",
                    source=Identifier("items"),
                    var="x",
                    predicate=Literal(True),
                )
            )
        )
        self.assertTrue(
            is_boolean_expr(
                IsOfExpr(
                    source=Identifier("a"),
                    type_ref=type_ref,
                )
            )
        )

    def test_boolean_heuristic_for_function_calls(self) -> None:
        self.assertTrue(is_boolean_expr(FunctionCall("contains", [Literal("a")])))
        self.assertTrue(is_boolean_expr(FunctionCall("EndsWith", [Literal("a")])))
        self.assertFalse(is_boolean_expr(FunctionCall("length", [Literal("a")])))
