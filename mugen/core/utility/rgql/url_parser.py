"""Parsing of RGQL-style URLs into structured objects.

A URL is broken down into:

* the raw URL string
* a list of path segments describing the resource path
* a bundle of query options (filter, orderby, select, expand, apply,
  search, paging, and parameter aliases)

This module focuses purely on syntactic structure; model- and
type-specific validation is handled by the semantic layer.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse, parse_qsl

from mugen.core.utility.rgql.apply_parser import (
    parse_apply,
    ApplyNode,
    ComputeExpression,
    parse_compute_option,
)
from mugen.core.utility.rgql.ast import Expr, is_boolean_expr
from mugen.core.utility.rgql.expr_parser import parse_rgql_expr, ParseError
from mugen.core.utility.rgql.orderby_parser import parse_orderby, OrderByItem
from mugen.core.utility.rgql.search_parser import parse_rgql_search, SearchExpr


@dataclass
class ExpandItem:  # pylint: disable=too-many-instance-attributes
    """One item inside a ``$expand`` query option.

    ``path`` identifies the navigation path to be expanded relative to
    the base entity type (e.g. ``"Orders/Items"``) or the wildcard
    ``"*"``, which means "all navigation properties" at that level.
    The remaining fields correspond to per-expand options that further
    shape what is returned for that navigation property: nested filters,
    ordering, projection, nested expands, paging controls, inline
    search, and recursive expansion levels.

    All option fields are optional and default to ``None`` when not
    specified in the query string.
    """

    path: str  # navigation path, e.g. "Orders/Items" or "*"
    is_ref: bool = False

    filter: Optional[Expr] = None
    orderby: Optional[List[OrderByItem]] = None
    select: Optional[List[str]] = None
    expand: Optional[List["ExpandItem"]] = None
    top: Optional[int] = None
    skip: Optional[int] = None
    count: Optional[bool] = None
    search: Optional[SearchExpr] = None
    levels: Optional[Any] = None  # int or "max"


@dataclass
class KeyComponent:
    """
    One component of a key predicate.

    For positional keys:

        Customers(1)  -> name=None, expr=<Literal 1>

    For named composite keys:

        OrderItems(OrderId=1,ProductId=2)
            -> [KeyComponent("OrderId", <Literal 1>),
                KeyComponent("ProductId", <Literal 2>)]
    """

    name: Optional[str]  # None for positional single-key form
    expr: Expr


@dataclass
class RGQLPathSegment:
    """
    One segment of the resource path:

        Customers(1)   -> name="Customers", key_predicate="1"
        Orders         -> name="Orders"
        $count         -> name="$count", is_count=True
    """

    name: str
    key_predicate: Optional[str] = None  # raw text for debugging / logging
    key_components: Optional[List[KeyComponent]] = None  # parsed structure
    is_count: bool = False


@dataclass
class RGQLQueryOptions:  # pylint: disable=too-many-instance-attributes
    """Parsed query options extracted from the URL.

    Each attribute corresponds to a well-known option:

      * ``filter``       -- root expression for ``$filter``
      * ``orderby``      -- list of :class:`OrderByItem` (``$orderby``)
      * ``select``       -- list of property paths (``$select``)
      * ``expand``       -- list of :class:`ExpandItem` (``$expand``)
      * ``apply``        -- list of :class:`ApplyNode` (``$apply``)
      * ``compute``      -- list of :class:`ComputeExpression` (``$compute``)
      * ``search``       -- root of the search AST (``$search``)
      * ``top``          -- integer value from ``$top``
      * ``skip``         -- integer value from ``$skip``
      * ``count``        -- boolean from ``$count``
      * ``format``       -- raw value of ``$format`` (usually a media type)
      * ``skiptoken``    -- opaque paging token from ``$skiptoken``
      * ``deltatoken``   -- opaque delta token from ``$deltatoken``
      * ``schemaversion``-- version string from ``$schemaversion``

    ``param_aliases`` collects parameter alias definitions such as
    ``@p1=10`` or ``@address={...}``, mapped to parsed expression trees.
    """

    filter: Optional[Expr] = None
    orderby: Optional[List[OrderByItem]] = None
    select: Optional[List[str]] = None
    expand: Optional[List[ExpandItem]] = None
    apply: Optional[List[ApplyNode]] = None
    compute: Optional[List[ComputeExpression]] = None
    search: Optional[SearchExpr] = None
    top: Optional[int] = None
    skip: Optional[int] = None
    count: Optional[bool] = None

    # Extra system query options (kept as raw strings)
    format: Optional[str] = None  # $format
    skiptoken: Optional[str] = None  # $skiptoken
    deltatoken: Optional[str] = None  # $deltatoken
    schemaversion: Optional[str] = None  # $schemaversion

    # Parameter aliases, e.g. ?$filter=Price gt @p1&@p1=10
    param_aliases: Dict[str, Expr] = field(default_factory=dict)


@dataclass
class RGQLUrl:
    """Parsed representation of a RGQL-style URL.

    The structure mirrors the logical pieces of the URL:

      * ``raw_url`` - original text form
      * ``path`` - path part as text (e.g. ``"/Customers(1)/Orders"``)
      * ``resource_path`` - parsed path as a list of
        :class:`RGQLPathSegment` instances
      * ``query`` - parsed query options as a :class:`RGQLQueryOptions`
        instance

    This class is purely structural; higher layers decide how to execute
    or interpret the parsed URL.
    """

    raw_url: str
    path: str
    resource_path: List[RGQLPathSegment]
    query: RGQLQueryOptions


# ----------------------------------------------------------------------
# $expand parsing helpers
# ----------------------------------------------------------------------


def _split_top_level(text: str, delim: str) -> List[str]:
    """
    Split on delim (',' or ';') at *top level* only, ignoring instances
    inside parentheses, JSON objects/arrays, or single-quoted strings.
    """
    parts: List[str] = []
    buf: List[str] = []
    in_string = False
    depth = 0  # counts (), {}, []

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

            if ch == delim and depth == 0:
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
    return _split_top_level(text, ",")


def _split_semicolons_top_level(text: str) -> List[str]:
    return _split_top_level(text, ";")


def _split_expand_item(text: str) -> tuple[str, Optional[str]]:
    """
    Split "Orders($filter=...;$expand=Items)" into ("Orders", "$filter=...;$expand=Items")
    """
    text = text.strip()
    in_string = False
    paren_depth = 0
    start_opt: Optional[int] = None

    for i, ch in enumerate(text):
        if ch == "'":
            if in_string and i + 1 < len(text) and text[i + 1] == "'":
                continue
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "(":
            if paren_depth == 0:
                start_opt = i
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
            if paren_depth < 0:
                raise ParseError(f"Unbalanced ')' in $expand item: {text!r}")
            if paren_depth == 0 and start_opt is not None:
                path = text[:start_opt].strip()
                options = text[start_opt + 1 : i].strip()
                rest = text[i + 1 :].strip()
                if rest:
                    raise ParseError(
                        f"Unexpected characters after expand options in: {text!r}"
                    )
                return path, options

    if paren_depth != 0:
        raise ParseError(f"Unbalanced '(' in $expand item: {text!r}")

    return text, None


def _parse_key_predicate(text: str) -> List[KeyComponent]:
    """
    Parse the contents of a key predicate into components.

    Supports:
      - positional single-key form: "1" or "'ABC'"
      - named composite form: "OrderId=1,ProductId=2"

    Each value is parsed using the full expression parser so
    parameter aliases and other literal forms are allowed.
    """
    text = text.strip()
    if not text:
        raise ParseError("Empty key predicate '()' is not allowed")

    parts = _split_commas_top_level(text)
    components: List[KeyComponent] = []

    for part in parts:
        part = part.strip()
        if not part:
            raise ParseError(f"Empty key component in predicate: {text!r}")

        if "=" in part:
            name_str, value_str = part.split("=", 1)
            name = name_str.strip()
            if not name:
                raise ParseError(f"Missing key name in component: {part!r}")
            value_text = value_str.strip()
        else:
            # positional single-key form
            name = None
            value_text = part

        try:
            expr = parse_rgql_expr(value_text)
        except ParseError as exc:
            raise ParseError(f"Invalid key value {value_text!r}: {exc}") from exc

        components.append(KeyComponent(name=name, expr=expr))

    return components


# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
def _parse_expand_options(item: ExpandItem, options: str) -> None:
    if not options:
        return

    for opt_str in _split_semicolons_top_level(options):
        if not opt_str:
            continue
        if "=" not in opt_str:
            raise ParseError(f"Invalid expand option: {opt_str!r}")

        name_part, value_part = opt_str.split("=", 1)
        name = name_part.strip()
        value = value_part.strip()

        if name.startswith("$"):
            name = name[1:]
        name_lower = name.lower()

        if name_lower == "filter":
            expr = parse_rgql_expr(value)
            if not is_boolean_expr(expr):
                raise ParseError("$filter in $expand must be boolean")
            item.filter = expr
            continue

        if name_lower == "orderby":
            item.orderby = parse_orderby(value)
            continue

        if name_lower == "select":
            cols = [p.strip() for p in _split_commas_top_level(value) if p.strip()]
            item.select = cols
            continue

        if name_lower == "expand":
            item.expand = parse_expand(value)
            continue

        if name_lower == "top":
            try:
                item.top = int(value)
            except ValueError as exc:
                raise ParseError(f"Invalid $top value in $expand: {value!r}") from exc
            continue

        if name_lower == "skip":
            try:
                item.skip = int(value)
            except ValueError as exc:
                raise ParseError(f"Invalid $skip value in $expand: {value!r}") from exc
            continue

        if name_lower == "count":
            v = value.lower()
            if v == "true":
                item.count = True
            elif v == "false":
                item.count = False
            else:
                raise ParseError(f"Invalid $count value in $expand: {value!r}")
            continue

        if name_lower == "search":
            item.search = parse_rgql_search(value)
            continue

        if name_lower == "levels":
            if value.lower() == "max":
                item.levels = "max"
            else:
                try:
                    item.levels = int(value)
                except ValueError as exc:
                    raise ParseError(
                        f"Invalid $levels value in $expand: {value!r}"
                    ) from exc
            continue

        raise ParseError(f"Unsupported expand option: {name_part!r}")


def parse_expand(expand_value: str) -> List[ExpandItem]:
    """Parse the value of a ``$expand`` query option into a list of
    :class:`ExpandItem` objects.

    The input is the raw text that appears on the right-hand side of
    ``$expand=`` in a query string. The syntax supports:

      * comma-separated expand items, e.g. ``Orders,Orders/Items``
      * optional per-item option blocks in parentheses, such as::

            Orders($filter=Status eq 'Open';$top=5)

      * nested expands via ``$expand=...`` inside the option block
      * the special ``/$ref`` suffix to request references instead of full
        entities
      * the wildcard ``*`` to expand all navigation properties at a
        given level, e.g. ``$expand=*`` or ``Orders($expand=*)``

    Each top-level item is turned into an :class:`ExpandItem` with:

      * ``path`` set to the navigation path (without any ``/$ref`` suffix)
      * ``is_ref`` indicating whether ``/$ref`` was present
      * additional per-item options (``filter``, ``orderby``, ``select``,
        ``expand``, ``top``, ``skip``, ``count``, ``search``, ``levels``)
        populated by :func:`_parse_expand_options`.

    Parameters
    ----------
    expand_value:
        Raw value of the ``$expand`` option, without the leading
        ``"$expand="`` prefix.

    Returns
    -------
    list of ExpandItem
        One :class:`ExpandItem` instance for each top-level expand item, in
        the order they were specified.

    Raises
    ------
    ParseError
        If the text is syntactically invalid (unbalanced parentheses,
        empty paths, malformed options, or unsupported option names).
    """
    items: List[ExpandItem] = []
    for item_str in _split_commas_top_level(expand_value):
        if not item_str:
            continue

        path, options = _split_expand_item(item_str)
        is_ref = False
        if path.endswith("/$ref"):
            is_ref = True
            path = path[:-5].rstrip("/")

        if not path:
            raise ParseError(f"Empty path in $expand item: {item_str!r}")

        item = ExpandItem(path=path, is_ref=is_ref)
        if options:
            _parse_expand_options(item, options)
        items.append(item)
    return items


# ----------------------------------------------------------------------
# URL parsing
# ----------------------------------------------------------------------


def _parse_path(path: str) -> List[RGQLPathSegment]:
    parts = [p for p in path.split("/") if p]
    segments: List[RGQLPathSegment] = []

    for p in parts:
        if p == "$count":
            segments.append(RGQLPathSegment(name="$count", is_count=True))
            continue

        name = p
        key_predicate: Optional[str] = None
        key_components: Optional[List[KeyComponent]] = None

        if p.endswith(")") and "(" in p:
            idx = p.index("(")
            name = p[:idx]
            key_predicate = p[idx + 1 : -1]
            # May raise ParseError on malformed keys, which is correct.
            key_components = _parse_key_predicate(key_predicate)

        segments.append(
            RGQLPathSegment(
                name=name,
                key_predicate=key_predicate,
                key_components=key_components,
            )
        )

    return segments


def parse_rgql_url(url: str) -> RGQLUrl:
    """Parse a RGQL-style URL into an :class:`RGQLUrl` structure.

    The function:

      * uses :func:`urllib.parse.urlparse` to split the URL
      * parses the path into :class:`RGQLPathSegment` objects
      * parses recognized query options (``$filter``, ``$orderby``,
        ``$select``, ``$expand``, ``$search``, ``$apply``, ``$compute``,
        ``$top``, ``$skip``, ``$count``) using the dedicated parsers in this
        package
      * collects parameter aliases of the form ``@name=value``

    Unrecognized query options are currently ignored.  Any syntactic
    error in the path or in a recognized query option results in a
    :class:`ParseError`.
    """
    parsed = urlparse(url)
    path = parsed.path or ""
    resource_path = _parse_path(path)

    opts = RGQLQueryOptions()
    for raw_name, raw_value in parse_qsl(parsed.query, keep_blank_values=True):
        if not raw_name:
            continue

        value = raw_value

        # Parameter alias, e.g. @p1=10 or @address={...}
        if raw_name.startswith("@"):
            if not value:
                raise ParseError(f"Parameter alias {raw_name!r} must have a value")
            if raw_name in opts.param_aliases:
                raise ParseError(f"Duplicate parameter alias {raw_name!r}")
            alias_expr = parse_rgql_expr(value)
            opts.param_aliases[raw_name] = alias_expr
            continue

        # System query options: support both "$filter" and "filter", case-insensitive
        name_norm = raw_name[1:] if raw_name.startswith("$") else raw_name
        name_lower = name_norm.lower()

        if name_lower == "filter":
            expr = parse_rgql_expr(value)
            if not is_boolean_expr(expr):
                raise ParseError("$filter expression must be boolean")
            if opts.filter is not None:
                raise ParseError("Duplicate $filter")
            opts.filter = expr

        elif name_lower == "orderby":
            if opts.orderby is not None:
                raise ParseError("Duplicate $orderby")
            opts.orderby = parse_orderby(value)

        elif name_lower == "select":
            if opts.select is not None:
                raise ParseError("Duplicate $select")
            cols = [p.strip() for p in _split_commas_top_level(value) if p.strip()]
            opts.select = cols

        elif name_lower == "expand":
            if opts.expand is not None:
                raise ParseError("Duplicate $expand")
            opts.expand = parse_expand(value)

        elif name_lower == "search":
            if opts.search is not None:
                raise ParseError("Duplicate $search")
            opts.search = parse_rgql_search(value)

        elif name_lower == "apply":
            if opts.apply is not None:
                raise ParseError("Duplicate $apply")
            opts.apply = parse_apply(value)

        elif name_lower == "compute":
            if opts.compute is not None:
                raise ParseError("Duplicate $compute")
            opts.compute = parse_compute_option(value)

        elif name_lower == "top":
            if opts.top is not None:
                raise ParseError("Duplicate $top")
            try:
                opts.top = int(value)
            except ValueError as exc:
                raise ParseError(f"Invalid $top value: {value!r}") from exc

        elif name_lower == "skip":
            if opts.skip is not None:
                raise ParseError("Duplicate $skip")
            try:
                opts.skip = int(value)
            except ValueError as exc:
                raise ParseError(f"Invalid $skip value: {value!r}") from exc

        elif name_lower == "count":
            if opts.count is not None:
                raise ParseError("Duplicate $count")
            v = value.lower()
            if v == "true":
                opts.count = True
            elif v == "false":
                opts.count = False
            else:
                raise ParseError(f"Invalid $count value: {value!r}")

        elif name_lower == "format":
            if opts.format is not None:
                raise ParseError("Duplicate $format")
            opts.format = value

        elif name_lower == "skiptoken":
            if opts.skiptoken is not None:
                raise ParseError("Duplicate $skiptoken")
            opts.skiptoken = value

        elif name_lower == "deltatoken":
            if opts.deltatoken is not None:
                raise ParseError("Duplicate $deltatoken")
            opts.deltatoken = value

        elif name_lower == "schemaversion":
            if opts.schemaversion is not None:
                raise ParseError("Duplicate $schemaversion")
            opts.schemaversion = value

        else:
            # Unknown query option – ignored for now, or could be recorded.
            pass

    return RGQLUrl(
        raw_url=url,
        path=path,
        resource_path=resource_path,
        query=opts,
    )
