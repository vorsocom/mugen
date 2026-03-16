"""Unit tests for RGQL boolean normalization helpers."""

import unittest

from mugen.core.utility.rgql.ast import BinaryOp, Identifier, Literal, UnaryOp
from mugen.core.utility.rgql.boolean_normalizer import (
    _dnf_from_nnf,
    _nnf,
    _bool_value,
    dnf_clauses_to_ast,
    simplify_boolean,
    to_dnf_clauses,
    to_nnf,
)


class TestMugenRgqlBooleanNormalizer(unittest.TestCase):
    """Covers simplification, NNF, DNF, and reconstruction behavior."""

    def test_simplify_boolean_handles_literals_not_and_double_not(self) -> None:
        lit = Literal(True)
        self.assertIs(simplify_boolean(lit), lit)
        self.assertEqual(simplify_boolean(UnaryOp("not", Literal(True))), Literal(False))
        self.assertEqual(
            simplify_boolean(UnaryOp("not", UnaryOp("not", Identifier("x")))),
            Identifier("x"),
        )
        self.assertEqual(
            simplify_boolean(UnaryOp("not", Identifier("x"))),
            UnaryOp("not", Identifier("x")),
        )

    def test_simplify_boolean_constant_folding_and_flattening(self) -> None:
        a = Identifier("a")
        b = Identifier("b")
        c = Identifier("c")
        self.assertEqual(simplify_boolean(BinaryOp("and", Literal(True), a)), a)
        self.assertEqual(
            simplify_boolean(BinaryOp("and", Literal(False), a)),
            Literal(False),
        )
        self.assertEqual(simplify_boolean(BinaryOp("or", Literal(False), a)), a)
        self.assertEqual(simplify_boolean(BinaryOp("or", Literal(True), a)), Literal(True))
        self.assertEqual(simplify_boolean(BinaryOp("and", a, Literal(True))), a)
        self.assertEqual(
            simplify_boolean(BinaryOp("and", a, Literal(False))),
            Literal(False),
        )
        self.assertEqual(simplify_boolean(BinaryOp("or", a, Literal(False))), a)
        self.assertEqual(simplify_boolean(BinaryOp("or", a, Literal(True))), Literal(True))

        flattened = simplify_boolean(
            BinaryOp("and", a, BinaryOp("and", b, c)),
        )
        self.assertEqual(
            flattened,
            BinaryOp("and", BinaryOp("and", a, b), c),
        )

    def test_to_nnf_and_internal_nnf_cover_negation_rules(self) -> None:
        a = Identifier("a")
        b = Identifier("b")

        self.assertEqual(to_nnf(UnaryOp("not", Literal(True))), Literal(False))
        self.assertEqual(
            to_nnf(UnaryOp("not", BinaryOp("and", a, b))),
            BinaryOp("or", UnaryOp("not", a), UnaryOp("not", b)),
        )
        self.assertEqual(
            _nnf(BinaryOp("or", a, b), negate=False),
            BinaryOp("or", a, b),
        )
        self.assertEqual(
            _nnf(BinaryOp("or", a, b), negate=True),
            BinaryOp("and", UnaryOp("not", a), UnaryOp("not", b)),
        )
        self.assertEqual(_nnf(a, negate=True), UnaryOp("not", a))
        self.assertEqual(_nnf(a, negate=False), a)

    def test_dnf_conversion_and_non_boolean_rejection(self) -> None:
        a = Identifier("a")
        b = Identifier("b")
        c = Identifier("c")

        with self.assertRaisesRegex(ValueError, "not boolean"):
            to_dnf_clauses(Literal("nope"))

        self.assertEqual(to_dnf_clauses(Literal(False)), [])
        self.assertEqual(to_dnf_clauses(Literal(True)), [[]])

        # (a and b) or c -> [[a,b],[c]]
        expr = BinaryOp("or", BinaryOp("and", a, b), c)
        clauses = to_dnf_clauses(expr)
        self.assertEqual(clauses, [[a, b], [c]])

        # (True) or c => tautology
        taut = BinaryOp("or", Literal(True), c)
        self.assertEqual(to_dnf_clauses(taut), [[]])

    def test_internal_dnf_from_nnf_cases(self) -> None:
        a = Identifier("a")
        b = Identifier("b")
        c = Identifier("c")

        self.assertEqual(_dnf_from_nnf(Literal(True)), [[]])
        self.assertEqual(_dnf_from_nnf(Literal(False)), [])
        self.assertEqual(_dnf_from_nnf(a), [[a]])
        self.assertEqual(
            _dnf_from_nnf(BinaryOp("and", BinaryOp("or", a, b), c)),
            [[a, c], [b, c]],
        )
        self.assertEqual(_dnf_from_nnf(BinaryOp("or", a, b)), [[a], [b]])

    def test_dnf_clauses_to_ast_roundtrip_shapes(self) -> None:
        a = Identifier("a")
        b = Identifier("b")
        c = Identifier("c")

        self.assertEqual(dnf_clauses_to_ast([]), Literal(False))
        self.assertEqual(dnf_clauses_to_ast([[]]), Literal(True))
        self.assertEqual(
            dnf_clauses_to_ast([[a, b]]),
            BinaryOp("and", a, b),
        )
        self.assertEqual(
            dnf_clauses_to_ast([[a], [b]]),
            BinaryOp("or", a, b),
        )
        self.assertEqual(
            dnf_clauses_to_ast([[a, b], [c]]),
            BinaryOp("or", BinaryOp("and", a, b), c),
        )
        self.assertEqual(
            dnf_clauses_to_ast([[], [a]]),
            BinaryOp("or", Literal(True), a),
        )

    def test_bool_value_rejects_non_boolean_literal(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected boolean literal expression"):
            _bool_value(Literal("not-boolean"))
