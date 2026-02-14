"""Parser for $orderby-style sort clauses.

The syntax is a comma-separated list of expressions, each optionally
followed by ``asc`` or ``desc``.  This module turns the textual
representation into :class:`OrderByItem` objects that can be consumed by
the semantic checker or execution engine.
"""

from dataclasses import dataclass
from typing import List

from mugen.core.utility.rgql.expr_parser import parse_rgql_expr, ParseError
from mugen.core.utility.rgql.ast import Expr


@dataclass
class OrderByItem:
    """One sort key inside a ``$orderby`` clause.

    Attributes
    ----------
    expr:
        Full RGQL expression whose value is used as the sort key.
    direction:
        Either ``"asc"`` (ascending) or ``"desc"`` (descending).  If the
        direction is omitted in the input, it defaults to ``"asc"``.
    """

    expr: Expr
    direction: str  # "asc" or "desc"


def _split_commas_top_level(text: str) -> List[str]:
    """
    Split on ',' at top level, ignoring commas in:
      - parentheses
      - JSON objects/arrays
      - single-quoted strings
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


def parse_orderby(text: str) -> List[OrderByItem]:
    """
    Parse $orderby into a list of OrderByItem.

    Each item is of the form:

        expr [asc|desc]
    """
    items: List[OrderByItem] = []
    for part in _split_commas_top_level(text):
        s = part.strip()

        direction = "asc"
        lower = s.lower()
        if lower.endswith(" asc"):
            direction = "asc"
            expr_text = s[:-4].rstrip()
        elif lower.endswith(" desc"):
            direction = "desc"
            expr_text = s[:-5].rstrip()
        elif lower in {"asc", "desc"}:
            direction = lower
            expr_text = ""
        else:
            expr_text = s

        if not expr_text:
            raise ParseError(f"Missing expression in $orderby segment: {part!r}")

        expr = parse_rgql_expr(expr_text)
        items.append(OrderByItem(expr=expr, direction=direction))

    return items
