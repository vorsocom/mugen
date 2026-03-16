"""Parser for $apply-style transformation pipelines.

A value such as::

    $apply=groupby((Category),aggregate(Amount with sum as Total))/topcount(5)

is treated as a *pipeline* of transformations separated by ``"/"``.
This module turns that textual representation into a tree of :class:`ApplyNode`
instances that can be interpreted by the semantic layer or execution
engine.

Only syntax is handled here; no type checking or model validation is
performed.
"""

from dataclasses import dataclass
from typing import List, Optional

from mugen.core.utility.rgql.expr_parser import parse_rgql_expr, ParseError
from mugen.core.utility.rgql.ast import Expr, is_boolean_expr
from mugen.core.utility.rgql.orderby_parser import parse_orderby, OrderByItem
from mugen.core.utility.rgql.search_parser import parse_rgql_search

# ----------------------------------------------------------------------
# AST for $apply
# ----------------------------------------------------------------------


class ApplyNode:  # pylint: disable=too-few-public-methods
    """Parser for $apply-style transformation pipelines.

    A value such as::

        $apply=groupby((Category),aggregate(Amount with sum as Total))/topcount(5)

    is treated as a *pipeline* of transformations separated by ``"/"``.
    This module turns that textual representation into a tree of :class:`ApplyNode`
    instances that can be interpreted by the semantic layer or execution
    engine.

    Only syntax is handled here; no type checking or model validation is
    performed.
    """


@dataclass
class AggregateExpression:
    """Single aggregate expression inside an ``aggregate(...)`` transform.

    There are two shapes:

      * value aggregate::

            Amount with sum as Total

        where ``expr`` is the value expression, ``method`` is the aggregate
        method name (e.g. ``"sum"`` or ``"max"``), and ``alias`` is an
        optional name for the computed value.

      * count aggregate::

            $count as TotalCount

        where ``is_count`` is ``True`` and ``expr``/``method`` are ``None``.

    The parser does not interpret aggregate method names – they are
    passed through as strings to be interpreted later.
    """

    expr: Optional[Expr]  # None for $count
    method: Optional[str]  # "sum", "min", "max", ...
    alias: Optional[str]
    is_count: bool = False


@dataclass
class AggregateTransform(ApplyNode):
    """``aggregate(...)`` transformation.

    ``aggregates`` is the list of :class:`AggregateExpression` items,
    each describing one computed measure (or a count).  The transform as
    a whole is applied to the input sequence.
    """

    aggregates: List[AggregateExpression]


@dataclass
class GroupByTransform(ApplyNode):
    """``groupby(...)`` transformation.

    Attributes
    ----------
    grouping_paths:
        List of property paths (relative to the input element) that
        define the grouping keys, e.g. ``["Category", "Customer/Country"]``.
    sub_transforms:
        Optional nested transformation pipeline to be evaluated *per
        group* after grouping has been applied.  This allows constructs
        such as ``groupby((Category), aggregate(...))``.
    """

    grouping_paths: List[str]
    sub_transforms: Optional[List[ApplyNode]] = None


@dataclass
class BottomTopTransform(ApplyNode):
    """Family of transformations that select the "top" or "bottom" N items.

    ``kind`` distinguishes the specific variant, for example::

        "topcount", "bottomcount", "toppercent", "bottompercent",
        "topsum", "bottomsum"

    ``n_expr`` is the expression determining the number of items (or
    percentage / sum threshold, depending on the variant).

    ``value_expr`` is the value used for ordering or accumulation when
    choosing the items.
    """

    kind: str  # topcount, bottomcount, toppercent, ...
    n_expr: Expr
    value_expr: Expr


@dataclass
class FilterTransform(ApplyNode):
    """``filter(<predicate>)`` transformation.

    ``predicate`` is a full RGQL expression that is required to evaluate
    to a boolean value.  Only items for which the predicate is true are
    kept in the result sequence.
    """

    predicate: Expr


@dataclass
class OrderByTransform(ApplyNode):
    """``orderby(...)`` transformation.

    ``items`` is the list of :class:`~mugen.core.utility.rgql_parser.orderby_parser.OrderByItem`
    produced by the order-by parser, describing the sort keys and their
    directions.
    """

    items: List[OrderByItem]


@dataclass
class SearchTransform(ApplyNode):
    """``search(...)`` transformation.

    ``search`` is the root of the search expression AST produced by
    :func:`parse_rgql_search`.  The semantic layer decides how this
    abstract search tree maps to concrete fields or full-text indices.
    """

    search: object


@dataclass
class SkipTransform(ApplyNode):
    """``skip(N)`` transformation.

    Skips the first ``N`` items of the input sequence.  ``count`` must
    be a non-negative integer; the parser enforces this.
    """

    count: int


@dataclass
class TopTransform(ApplyNode):
    """``top(N)`` transformation.

    Keeps only the first ``N`` items of the input sequence.  ``count``
    must be a non-negative integer; the parser enforces this.
    """

    count: int


@dataclass
class IdentityTransform(ApplyNode):
    """``identity()`` transformation.

    This is a no-op step used mainly for testing and as a placeholder in
    some transformation pipelines.  It leaves the input sequence
    unchanged.
    """


@dataclass
class ComputeExpression:
    """Single computed expression inside ``compute(...)``.

    Each expression has the shape::

        <expr> as <alias>

    where ``expr`` is a full RGQL expression and ``alias`` is the name
    bound to the computed value in the result.
    """

    expr: Expr
    alias: str


@dataclass
class ComputeTransform(ApplyNode):
    """``compute(...)`` transformation.

    ``computes`` is a list of :class:`ComputeExpression` items, each
    introducing a new computed value alongside the original input.
    The exact projection rules are defined by the execution engine.
    """

    computes: List[ComputeExpression]


@dataclass
class ConcatTransform(ApplyNode):
    """``concat(...)`` transformation.

    Represents a concatenation of multiple pipelines.  Each element of
    ``sequences`` is itself a list of :class:`ApplyNode` objects that
    form a sub-pipeline.  The result of each sub-pipeline is concatenated
    in order to produce the final result.
    """

    sequences: List[List[ApplyNode]]


@dataclass
class CustomApplyTransform(ApplyNode):
    """Fallback node for custom or unrecognized transformations.

    If a transformation name is not one of the built-in forms understood
    by this module, it is represented as ``CustomApplyTransform`` so that
    callers can still inspect and possibly interpret it.

    Attributes
    ----------
    name:
        The transformation name as it appeared in the query.
    raw_args:
        The raw argument string between parentheses, without any parsing
        beyond balanced-parenthesis handling.
    """

    name: str
    raw_args: str


# ----------------------------------------------------------------------
# Top-level API
# ----------------------------------------------------------------------


def parse_apply(apply_value: str) -> List[ApplyNode]:
    """Parse a textual $apply transformation pipeline into a list of
    :class:`ApplyNode` instances.

    The input is the raw value of the ``$apply`` query option *without*
    the leading ``"$apply="``.  The function:

      1. splits the text into top-level segments on ``"/"`` while
         respecting parentheses, JSON literals, and strings
      2. parses each segment into the appropriate concrete subclass of
         :class:`ApplyNode`
      3. returns the resulting list in order

    Any syntax error (unbalanced parentheses, missing keywords, invalid
    arguments, etc.) results in a :class:`ParseError`.
    """
    segments = _split_apply_sequence(apply_value)
    if not segments:
        raise ParseError("Empty $apply value")
    transforms: List[ApplyNode] = []
    for seg in segments:
        transforms.append(_parse_single_transform(seg))
    return transforms


# ----------------------------------------------------------------------
# Splitting helpers
# ----------------------------------------------------------------------


def _split_apply_sequence(text: str) -> List[str]:
    """
    Split a transformation sequence on '/' at top level, ignoring '/' that
    occur inside parentheses, JSON objects/arrays, or strings.
    """
    parts: List[str] = []
    buf: List[str] = []
    in_string = False
    depth = 0
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch == "'":
            buf.append(ch)
            if in_string and i + 1 < n and text[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue

        if not in_string:
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                depth = max(depth - 1, 0)

            if ch == "/" and depth == 0:
                part = "".join(buf).strip()
                if part:
                    parts.append(part)
                buf = []
                i += 1
                continue

        buf.append(ch)
        i += 1

    if buf:
        part = "".join(buf).strip()
        if part:
            parts.append(part)

    return parts


def _split_commas_top_level(text: str) -> List[str]:
    """
    Split on ',' at top level, ignoring commas in parentheses, JSON, or strings.
    """
    parts: List[str] = []
    buf: List[str] = []
    in_string = False
    depth = 0
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch == "'":
            buf.append(ch)
            if in_string and i + 1 < n and text[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue

        if not in_string:
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                depth = max(depth - 1, 0)
            if ch == "," and depth == 0:
                part = "".join(buf).strip()
                if part:
                    parts.append(part)
                buf = []
                i += 1
                continue

        buf.append(ch)
        i += 1

    if buf:
        part = "".join(buf).strip()
        if part:
            parts.append(part)

    return parts


# ----------------------------------------------------------------------
# Transform parsing
# ----------------------------------------------------------------------


# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches
def _parse_single_transform(text: str) -> ApplyNode:
    text = text.strip()
    if not text:
        raise ParseError("Empty transformation segment in $apply")

    name_end = text.find("(")
    if name_end == -1 or not text.endswith(")"):
        raise ParseError(f"Invalid transformation syntax: {text!r}")

    name = text[:name_end].strip()
    args = text[name_end + 1 : -1].strip()
    name_lower = name.lower()

    if name_lower == "aggregate":
        return _parse_aggregate(args)
    if name_lower == "groupby":
        return _parse_groupby(args)
    if name_lower in {
        "topcount",
        "bottomcount",
        "toppercent",
        "bottompercent",
        "topsum",
        "bottomsum",
    }:
        return _parse_bottom_top(name_lower, args)
    if name_lower == "filter":
        return _parse_filter(args)
    if name_lower == "orderby":
        return _parse_orderby_transform(args)
    if name_lower == "search":
        return _parse_search_transform(args)
    if name_lower == "skip":
        return _parse_skip(args)
    if name_lower == "top":
        return _parse_top(args)
    if name_lower == "identity":
        return _parse_identity(args)
    if name_lower == "compute":
        return _parse_compute(args)
    if name_lower == "concat":
        return _parse_concat(args)

    return CustomApplyTransform(name=name, raw_args=args)


# ----------------------------------------------------------------------
# Aggregate
# ----------------------------------------------------------------------


def _parse_aggregate(args: str) -> AggregateTransform:
    pieces = _split_commas_top_level(args)
    if not pieces:
        raise ParseError("aggregate(...) must have at least one argument")

    aggs: List[AggregateExpression] = []

    for piece in pieces:
        s = piece.strip()
        if not s:
            continue

        if s.lower().startswith("$count"):
            as_index = _find_keyword_top_level(s, "as")
            if as_index is None:
                raise ParseError(f"$count aggregate must specify 'as' alias: {s!r}")
            alias_str = s[as_index + 2 :].strip()
            if not alias_str:
                raise ParseError(f"Missing alias after 'as' in aggregate: {s!r}")
            aggs.append(
                AggregateExpression(
                    expr=None,
                    method=None,
                    alias=alias_str,
                    is_count=True,
                )
            )
            continue

        with_index = _find_keyword_top_level(s, "with")
        if with_index is None:
            raise ParseError(f"aggregate expression must contain 'with': {s!r}")

        expr_str = s[:with_index].strip()
        rest = s[with_index + 4 :].strip()
        if not rest:
            raise ParseError(f"Missing method after 'with' in {s!r}")

        as_index = _find_keyword_top_level(rest, "as")
        if as_index is None:
            method_str = rest
            alias_str = None
        else:
            method_str = rest[:as_index].strip()
            alias_str = rest[as_index + 2 :].strip()
            if not alias_str:
                raise ParseError(f"Missing alias after 'as' in {s!r}")

        expr = parse_rgql_expr(expr_str)
        aggs.append(
            AggregateExpression(
                expr=expr,
                method=method_str,
                alias=alias_str,
                is_count=False,
            )
        )

    return AggregateTransform(aggregates=aggs)


def _find_keyword_top_level(text: str, keyword: str) -> Optional[int]:
    t = text
    k = keyword.lower()
    n = len(t)
    i = 0
    in_string = False
    paren_depth = 0

    while i < n:
        ch = t[i]

        if ch == "'":
            if in_string and i + 1 < n and t[i + 1] == "'":
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue

        if not in_string:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth = max(paren_depth - 1, 0)

            if paren_depth == 0:
                if t[i].lower() == k[0] and t[i : i + len(k)].lower() == k:
                    before_ok = i == 0 or not t[i - 1].isalnum()
                    after_idx = i + len(k)
                    after_ok = after_idx >= n or not t[after_idx].isalnum()
                    if before_ok and after_ok:
                        return i

        i += 1

    return None


# ----------------------------------------------------------------------
# groupby
# ----------------------------------------------------------------------


def _parse_groupby(args: str) -> GroupByTransform:
    args = args.strip()
    if not args.startswith("("):
        raise ParseError("groupby(...) must start with '(' for grouping paths")

    end = _match_closing_paren(args, 0)
    if end is None:
        raise ParseError(f"Unbalanced parentheses in groupby: {args!r}")

    inner_paths = args[1:end].strip()
    rest = args[end + 1 :].strip()

    grouping_paths = [
        p.strip() for p in _split_commas_top_level(inner_paths) if p.strip()
    ]

    sub_transforms: Optional[List[ApplyNode]] = None
    if rest:
        if not rest.startswith(","):
            raise ParseError(
                f"Expected ',' after groupby grouping paths, got: {rest!r}"
            )
        sub_transforms = parse_apply(rest[1:].strip())

    return GroupByTransform(
        grouping_paths=grouping_paths, sub_transforms=sub_transforms
    )


def _match_closing_paren(text: str, start_index: int) -> Optional[int]:
    if start_index >= len(text) or text[start_index] != "(":
        return None

    in_string = False
    depth = 0
    i = start_index
    n = len(text)
    while i < n:
        ch = text[i]

        if ch == "'":
            if in_string and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue

        if in_string:
            i += 1
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1

    return None


# ----------------------------------------------------------------------
# bottom/top family
# ----------------------------------------------------------------------


def _parse_bottom_top(kind: str, args: str) -> BottomTopTransform:
    pieces = _split_commas_top_level(args)
    if len(pieces) != 2:
        raise ParseError(f"{kind}(...) expects exactly 2 parameters")

    n_expr = parse_rgql_expr(pieces[0])
    value_expr = parse_rgql_expr(pieces[1])
    return BottomTopTransform(kind=kind, n_expr=n_expr, value_expr=value_expr)


# ----------------------------------------------------------------------
# filter / orderby / search / skip / top / identity
# ----------------------------------------------------------------------


def _parse_filter(args: str) -> FilterTransform:
    expr = parse_rgql_expr(args)
    if not is_boolean_expr(expr):
        raise ParseError(f"filter(...) predicate must be boolean: {args!r}")
    return FilterTransform(predicate=expr)


def _parse_orderby_transform(args: str) -> OrderByTransform:
    items = parse_orderby(args)
    return OrderByTransform(items=items)


def _parse_search_transform(args: str) -> SearchTransform:
    search_ast = parse_rgql_search(args)
    return SearchTransform(search=search_ast)


def _parse_skip(args: str) -> SkipTransform:
    try:
        count = int(args.strip())
    except ValueError as exc:
        raise ParseError(f"skip(...) expects an integer, got: {args!r}") from exc
    if count < 0:
        raise ParseError("skip(...) count must be non-negative")
    return SkipTransform(count=count)


def _parse_top(args: str) -> TopTransform:
    try:
        count = int(args.strip())
    except ValueError as exc:
        raise ParseError(f"top(...) expects an integer, got: {args!r}") from exc
    if count < 0:
        raise ParseError("top(...) count must be non-negative")
    return TopTransform(count=count)


def _parse_identity(args: str) -> IdentityTransform:
    if args.strip():
        raise ParseError("identity() does not take any arguments")
    return IdentityTransform()


# ----------------------------------------------------------------------
# compute
# ----------------------------------------------------------------------


def _parse_compute(args: str) -> ComputeTransform:
    pieces = _split_commas_top_level(args)
    if not pieces:
        raise ParseError("compute(...) must have at least one expression")

    computes: List[ComputeExpression] = []

    for piece in pieces:
        s = piece.strip()
        if not s:
            continue

        as_index = _find_keyword_top_level(s, "as")
        if as_index is None:
            raise ParseError(f"compute expression must contain 'as': {s!r}")

        expr_str = s[:as_index].strip()
        alias_str = s[as_index + 2 :].strip()
        if not alias_str:
            raise ParseError(f"Missing alias after 'as' in compute expression: {s!r}")

        expr = parse_rgql_expr(expr_str)
        computes.append(ComputeExpression(expr=expr, alias=alias_str))

    return ComputeTransform(computes=computes)


def parse_compute_option(text: str) -> List[ComputeExpression]:
    """Parse the value of a ``$compute`` system query option.

    The grammar matches the arguments of the ``compute(...)``
    transformation in ``$apply``.  Example::

        $compute=Price mul 2 as DoublePrice, concat(Name, ' (VIP)') as Label

    returns a list of :class:`ComputeExpression` instances corresponding
    to each ``<expr> as <alias>`` pair.
    """
    # Reuse the existing compute transform parser and expose only the
    # list of expressions, since ``$compute`` does not form a pipeline.
    transform = _parse_compute(text)
    return transform.computes


# ----------------------------------------------------------------------
# concat
# ----------------------------------------------------------------------


def _parse_concat(args: str) -> ConcatTransform:
    pieces = _split_commas_top_level(args)
    if not pieces:
        raise ParseError("concat(...) must have at least one parameter")

    sequences: List[List[ApplyNode]] = []
    for piece in pieces:
        seq_str = piece.strip()
        if not seq_str:
            continue
        sequences.append(parse_apply(seq_str))

    return ConcatTransform(sequences=sequences)
