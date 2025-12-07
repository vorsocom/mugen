"""Abstract syntax tree (AST) nodes for the RGQL expression language.

The expression parser builds instances of these classes to represent the
syntactic structure of filter/orderby/search/apply expressions.  The
semantic layer works purely in terms of this tree - none of the nodes
depend on metadata or runtime execution details.

The design goals are:

* keep nodes simple, immutable dataclasses where possible
* represent the original query faithfully (no implicit rewrites)
* make it straightforward to walk/transform the tree in your own code
"""

from dataclasses import dataclass
from typing import Any, List, Optional


class Expr:  # pylint: disable=too-few-public-methods
    """Base class for all expression nodes."""


@dataclass
class Literal(Expr):
    """
    Simple literal value.

    value is a Python object:
      - int / float / decimal.Decimal
      - str
      - bool
      - None
      - datetime/date/time/timedelta
      - uuid.UUID
      - bytes
      - dict / list for JSON complex/collection
      - float('nan') / float('inf'), etc.
    """

    value: Any


@dataclass
class Identifier(Expr):
    """Simple name reference in an expression.

    The meaning of the name depends on the surrounding context:

      * in a resource path or filter: usually a property of the current
        entity type (e.g. ``Price`` or ``Customer/Name`` via
        :class:`MemberAccess`)
      * in a lambda expression: the lambda iteration variable
      * as a standalone value: may be interpreted as a parameter,
        enum literal, or model-defined symbol by the semantic layer

    At the parsing stage an :class:`Identifier` is just the raw name
    string; no resolution to a concrete model element has taken place yet.
    """

    name: str


@dataclass
class MemberAccess(Expr):
    """Dotted member access on a base expression.

    Examples::

        Price            # Identifier("Price")
        Customer/Name    # MemberAccess(Identifier("Customer"), "Name")
        Address/City     # MemberAccess(Identifier("Address"), "City")

    The parser creates a chain of :class:`MemberAccess` nodes when it
    sees ``expr / member`` syntax.  The semantic checker later resolves
    each ``member`` against the type of ``base`` (structural property,
    navigation property, etc.).
    """

    base: Expr
    member: str


@dataclass
class BinaryOp(Expr):
    """Binary operator with a left and right operand.

    The ``op`` field uses a normalized, lower-case name rather than the
    surface syntax.  For example::

        Price gt 10      -> BinaryOp("gt",  Identifier("Price"), Literal(10))
        a and b          -> BinaryOp("and", <a>, <b>)
        Amount add Tax   -> BinaryOp("add", <Amount>, <Tax>)

    The set of operators is driven by the lexer and expression grammar
    (comparison, arithmetic, logical, and the enum-style ``has`` operator).
    The semantic checker is responsible for validating that each operator
    is applied to compatible operand types.
    """

    op: str
    left: Expr
    right: Expr


@dataclass
class UnaryOp(Expr):
    """Unary operator applied to a single operand.

    Typical examples include::

        not (Price gt 10)
        -Amount

    The ``op`` field is a normalized, lower-case name (for example
    ``"not"`` or ``"neg"``) chosen by the parser.  The precise set of
    supported unary operators is defined by the expression grammar.
    """

    op: str
    operand: Expr


@dataclass
class FunctionCall(Expr):
    """Function or method-style call.

    ``name`` is the textual name that appeared in the query and is kept
    as-is (case preserved).  Whether it represents a built-in function or
    a model-defined operation is left to the semantic layer.

    ``args`` is the list of positional arguments, each a full expression.

    Examples of calls that might produce this node::

        length(Name)
        concat(FirstName, ' ', LastName)
        my.namespace.customFunc(Price, 3)
    """

    name: str
    args: List[Expr]


@dataclass
class LambdaCall(Expr):
    """Lambda quantifier applied to a collection.

    This node represents constructs such as an ``any`` or ``all`` over a
    collection-valued expression.  The general shape is::

        <source>/<kind>(<var>: <predicate>)

    where:

      * ``kind`` is either ``"any"`` or ``"all"``
      * ``source`` is the collection on which the lambda runs
      * ``var`` is the lambda iteration variable name (may be ``None`` if
        the variable is omitted)
      * ``predicate`` is a boolean expression over ``var``; for ``any``,
        it may be ``None`` to represent the degenerate form ``any()``

    The semantic checker is responsible for verifying that ``source`` has
    a collection type and for typing the lambda variable.
    """

    kind: str  # "any" or "all"
    source: Expr  # collection expression
    var: Optional[str]  # lambda variable or None
    predicate: Optional[Expr]  # may be None for any()


@dataclass
class TypeRef:
    """
    Parsed type name from cast()/isof(), not the EDM model type.

    Examples of full_name:
      - "Edm.String"
      - "NS.Customer"
      - "Collection(NS.Customer)"
    """

    is_collection: bool
    namespace: Optional[str]
    name: str
    full_name: str


@dataclass
class CastExpr(Expr):
    """Explicit type cast expression.

    This is created for the ``cast(...)`` construct in the expression
    language.  Two main shapes are supported::

        cast(Property, NS.Customer)
        cast(NS.Customer)

    In the first form ``source`` is the expression being converted and
    ``type_ref`` is the target type.  In the second form ``source`` is
    ``None`` and the cast is interpreted as a type check or segment in
    a path; how it is handled depends on the caller.

    ``type_ref`` is purely syntactic (see :class:`TypeRef`) and is later
    resolved against the metadata model.
    """

    source: Optional[Expr]
    type_ref: TypeRef


@dataclass
class IsOfExpr(Expr):
    """Type test expression.

    Represents the ``isof(...)`` construct, which answers the question
    "is this value of (or derived from) the given type?".  The shapes are
    similar to :class:`CastExpr`::

        isof(Property, NS.Customer)
        isof(NS.Customer)

    When ``source`` is ``None`` the type test refers to the implicit
    context value, which is resolved by callers based on where the
    expression appears.
    """

    source: Optional[Expr]
    type_ref: TypeRef


@dataclass
class EnumLiteral(Expr):
    """
    Explicit enumeration literal:

        Namespace.Color'Red'
        Namespace.Color'Red,Green'
    """

    type_name: str
    values: List[str]


@dataclass
class SpatialLiteral(Expr):
    """
    Spatial literal:

        geography'SRID=4326;POINT(10 20)'
        geometry'POINT(10 20)'
    """

    is_geography: bool
    srid: Optional[int]
    wkt: str


# ----------------------------------------------------------------------
# Boolean-ness heuristic
# ----------------------------------------------------------------------


def is_boolean_expr(expr: Expr) -> bool:  # pylint: disable=too-many-return-statements
    """Heuristic that tries to decide whether an expression is intended to
    produce a boolean value.

    The parser itself is type-agnostic, so some higher-level checks
    (e.g. for query options that must be boolean) rely on this helper.
    The function looks at the *shape* of the AST rather than any
    metadata:

      * logical operators (and/or/not) and comparison operators
        usually yield ``True``/``False``
      * lambda calls (``any`` / ``all``) are treated as boolean
      * many built-in functions (e.g. ``contains``) are known to be
        boolean and are whitelisted
      * everything else is considered "maybe not boolean"

    This is intentionally conservative - it may return ``False`` for some
    expressions that are in fact boolean once typed.  The semantic layer
    performs the precise validation.
    """
    if isinstance(expr, Literal) and isinstance(expr.value, bool):
        return True

    if isinstance(expr, (LambdaCall, IsOfExpr)):
        return True

    if isinstance(expr, UnaryOp) and expr.op == "not":
        return is_boolean_expr(expr.operand)

    if isinstance(expr, BinaryOp):
        if expr.op in {"and", "or", "eq", "ne", "gt", "ge", "lt", "le", "has", "in"}:
            return True
        return False

    if isinstance(expr, Identifier):
        # Could be a boolean-valued property or alias
        return True

    return False
