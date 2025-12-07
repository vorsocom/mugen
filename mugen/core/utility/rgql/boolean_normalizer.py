"""Boolean normalization utilities for RGQL filter expressions.

This module provides helpers to transform RGQL boolean expressions
(typically from $filter, $expand(...;$filter=...), or $apply/filter)
into simpler, more backend-friendly forms.

The key goals are:

* Represent filters as a proper boolean expression tree
  (BinaryOp("and"/"or"), UnaryOp("not"), comparisons, function calls, etc.).
* Normalize that tree by:
    - Pushing NOTs down to the leaves (negation normal form, NNF).
    - Simplifying obvious boolean constants (True / False).
    - Flattening nested AND/OR chains.
* Convert normalized expressions into a disjunctive normal form (DNF)
  representation that is easy to map to relational queries.

The main entry point for backends is :func:`to_dnf_clauses`, which returns
a list of conjunctions (disjunctive groups):

    [[a, b], [c]]

represents the boolean formula:

    (a and b) or (c)

where each `a`, `b`, `c` is an RGQL AST node (:class:`Expr`) that can be
interpreted as an atomic predicate by the caller (e.g. a comparison, an
`in` expression, or a boolean-returning function call).

This structure is convenient for backends that want to:

* Run a single query with a complex OR condition,
* Or split a filter into multiple queries (one per group) and union the
  results,
* Or perform custom planning based on disjunctive groups.

Normalization here is purely syntactic and does not depend on model
metadata; it assumes that the input expression has already been validated
by the semantic checker and is known to be boolean.
"""

from typing import List

from mugen.core.utility.rgql.ast import (
    Expr,
    Literal,
    BinaryOp,
    UnaryOp,
    is_boolean_expr,
)

# ---------------------------------------------------------------------------
# Helpers to recognize boolean structure
# ---------------------------------------------------------------------------


def _is_bool_literal(expr: Expr) -> bool:
    return isinstance(expr, Literal) and isinstance(expr.value, bool)


def _bool_value(expr: Expr) -> bool:
    assert _is_bool_literal(expr)
    return bool(expr.value)


def _is_and(expr: Expr) -> bool:
    return isinstance(expr, BinaryOp) and expr.op == "and"


def _is_or(expr: Expr) -> bool:
    return isinstance(expr, BinaryOp) and expr.op == "or"


def _is_not(expr: Expr) -> bool:
    return isinstance(expr, UnaryOp) and expr.op == "not"


# ---------------------------------------------------------------------------
# Pass 1: Boolean simplification (constants, double-not, flattening)
# ---------------------------------------------------------------------------


# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches
def simplify_boolean(expr: Expr) -> Expr:
    """
    Recursively simplify boolean expressions by:

    * folding constant unary/binary operations
    * eliminating double negation (not (not X) -> X)
    * flattening nested and/or trees

    Non-boolean subexpressions are left as-is and treated as atoms.
    """
    # Literal: nothing to do
    if isinstance(expr, Literal):
        return expr

    # NOT
    if _is_not(expr):
        inner = simplify_boolean(expr.operand)

        # not True / not False
        if _is_bool_literal(inner):
            return Literal(not _bool_value(inner))

        # not (not X) -> X
        if _is_not(inner):
            return simplify_boolean(inner.operand)

        return UnaryOp("not", inner)

    # AND / OR
    if isinstance(expr, BinaryOp) and expr.op in {"and", "or"}:
        left = simplify_boolean(expr.left)
        right = simplify_boolean(expr.right)

        # Constant folding with boolean literals
        if _is_bool_literal(left):
            lv = _bool_value(left)
            if expr.op == "and":
                # True and X -> X, False and X -> False
                return right if lv else left
            else:  # or
                # True or X -> True, False or X -> X
                return left if lv else right

        if _is_bool_literal(right):
            rv = _bool_value(right)
            if expr.op == "and":
                return left if rv else right
            else:  # or
                return right if rv else left

        # Flatten nested same-operator trees: (A and (B and C)) -> (A and B and C)
        items: List[Expr] = []

        def collect(e: Expr) -> None:
            if isinstance(e, BinaryOp) and e.op == expr.op:
                collect(e.left)
                collect(e.right)
            else:
                items.append(e)

        collect(left)
        collect(right)

        if not items:
            # Shouldn't happen, but be defensive: treat as literal True
            return Literal(True)

        # Rebuild a left-associative tree: ((((i0 and i1) and i2) ...) and in)
        result = items[0]
        for item in items[1:]:
            result = BinaryOp(expr.op, result, item)
        return result

    # Generic recursion for other node types could be added here if you
    # introduce new expression forms. For now we treat them as atomic.
    return expr


# ---------------------------------------------------------------------------
# Pass 2: Push NOT down (Negation Normal Form)
# ---------------------------------------------------------------------------


def to_nnf(expr: Expr) -> Expr:
    """
    Convert a boolean expression into *negation normal form* (NNF), where
    'not' only appears directly on atomic subexpressions.

    This assumes 'and' / 'or' / 'not' are the only logical operators.
    Other operators (eq, ne, in, has, functions, etc.) are treated as atoms.
    """
    expr = simplify_boolean(expr)
    return _nnf(expr, negate=False)


def _nnf(expr: Expr, negate: bool) -> Expr:
    # Boolean literal
    if _is_bool_literal(expr):
        val = _bool_value(expr)
        return Literal(not val if negate else val)

    # NOT node
    if _is_not(expr):
        return _nnf(expr.operand, not negate)

    # AND / OR
    if isinstance(expr, BinaryOp) and expr.op in {"and", "or"}:
        if negate:
            # De Morgan: not (A and B) -> not A or not B, etc.
            new_op = "and" if expr.op == "or" else "or"
            left = _nnf(expr.left, True)
            right = _nnf(expr.right, True)
            return BinaryOp(new_op, left, right)
        else:
            left = _nnf(expr.left, False)
            right = _nnf(expr.right, False)
            return BinaryOp(expr.op, left, right)

    # Anything else: treat as an atomic predicate
    if negate:
        return UnaryOp("not", expr)
    return expr


# ---------------------------------------------------------------------------
# Pass 3: Extract DNF as “disjunctive groups”
# ---------------------------------------------------------------------------

DNFClauses = List[List[Expr]]
# Semantics: clauses = [[a1, a2], [b1], [c1, c2, c3]]
# represents: (a1 and a2) or (b1) or (c1 and c2 and c3)


def to_dnf_clauses(expr: Expr) -> DNFClauses:
    """
    Convert a boolean expression into Disjunctive Normal Form (DNF), returned
    as a list of conjunctions (disjunctive groups).

    Each inner list is a conjunction of *atomic* expressions or negated atoms:

        [[a, b], [c]]  ==>  (a and b) or (c)

    where "atoms" include:
      * comparison operators (eq, ne, gt, ge, lt, le, has, in, ...)
      * boolean-returning functions
      * arbitrary subexpressions wrapped in 'not' after NNF

    Constant results:
      * False -> []          (no groups)
      * True  -> [[]]        (single empty group, meaning "no filter")
    """
    if not is_boolean_expr(expr):
        raise ValueError("Expression is not boolean; cannot convert to DNF")

    nnf = to_nnf(expr)
    clauses = _dnf_from_nnf(nnf)

    # Optional: simplify tautological DNF (if True is present)
    # If we have an empty conjunction, the whole formula is True.
    if any(len(c) == 0 for c in clauses):
        return [[]]

    return clauses


def _dnf_from_nnf(expr: Expr) -> DNFClauses:
    # Base cases -------------------------------------------------------

    # Boolean literal
    if _is_bool_literal(expr):
        if _bool_value(expr):
            # True -> single empty conjunction
            return [[]]
        # False -> no clauses
        return []

    # AND
    if _is_and(expr):
        left_clauses = _dnf_from_nnf(expr.left)
        right_clauses = _dnf_from_nnf(expr.right)

        # Cross product of conjunctions
        result: DNFClauses = []
        for lc in left_clauses:
            for rc in right_clauses:
                result.append(lc + rc)
        return result

    # OR
    if _is_or(expr):
        left_clauses = _dnf_from_nnf(expr.left)
        right_clauses = _dnf_from_nnf(expr.right)
        return left_clauses + right_clauses

    # NOT or any other atom (in NNF, NOT only wraps atoms)
    return [[expr]]


# ---------------------------------------------------------------------------
# Optional: rebuild AST from DNF clauses
# ---------------------------------------------------------------------------


def dnf_clauses_to_ast(clauses: DNFClauses) -> Expr:
    """
    Rebuild an expression tree from DNF clauses.

        [[]]     -> Literal(True)
        []       -> Literal(False)
        [[a,b]]  -> a and b
        [[a],[b]] -> a or b
        [[a,b],[c]] -> (a and b) or c
    """
    if not clauses:
        return Literal(False)

    # Single empty group -> True
    if len(clauses) == 1 and len(clauses[0]) == 0:
        return Literal(True)

    # Build an 'and' chain for each clause
    def conj_to_expr(conj: List[Expr]) -> Expr:
        if not conj:
            return Literal(True)
        result = conj[0]
        for term in conj[1:]:
            result = BinaryOp("and", result, term)
        return result

    disj: List[Expr] = [conj_to_expr(c) for c in clauses]

    result = disj[0]
    for e in disj[1:]:
        result = BinaryOp("or", result, e)
    return result
