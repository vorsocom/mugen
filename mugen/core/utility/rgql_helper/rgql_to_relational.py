"""Adapter for translating RGQL queries into relational filter structures.

This module provides a thin integration layer between the RGQL query model
and the generic relational gateway contracts used by the storage layer.

The main entry point is :class:`RGQLToRelationalAdapter`, which converts
an :class:`~mugen.core.utility.rgql.url_parser.RGQLQueryOptions` instance
into the primitive structures understood by the RDBMS gateways:

* a sequence of :class:`FilterGroup` instances representing an OR-of-AND
  filter in disjunctive normal form (DNF);
* a sequence of :class:`OrderBy` descriptors derived from $orderby;
* optional ``limit`` and ``offset`` values derived from $top and $skip.

Property paths in the RGQL AST are expressed in EDM-style TitleCase form
(e.g. ``"UserId"``, ``"IsActive"``, or ``"Address/City"``).  This adapter
maps those paths to concrete column names by converting each segment from
TitleCase to snake_case using :func:`title_to_snake` and joining nested
segments with underscores (for example, ``"Address/City"`` becomes
``"address_city"``).

The adapter intentionally has no dependency on SQLAlchemy or any specific
database.  It produces only the abstract filter and ordering structures
defined in ``mugen.core.contract.gateway.storage.rdbms.types``, allowing
different relational backends to consume RGQL queries in a uniform way.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Sequence, Tuple

from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderClause,
    OrderBy,
    RelatedOrderBy,
    RelatedPathHop,
    RelatedScalarFilter,
    RelatedTextFilter,
    ScalarFilter,
    ScalarFilterOp,
    TextFilter,
    TextFilterOp,
)

from mugen.core.utility.string.case_conversion_helper import title_to_snake
from mugen.core.utility.rgql.ast import (
    Expr,
    BinaryOp,
    UnaryOp,
    Literal,
    Identifier,
    MemberAccess,
    FunctionCall,
)
from mugen.core.utility.rgql.boolean_normalizer import to_dnf_clauses
from mugen.core.utility.rgql.url_parser import RGQLQueryOptions, OrderByItem

PathPlanner = Callable[[str], tuple[Sequence[RelatedPathHop], str] | None]


def _is_literal(expr: Expr) -> bool:
    return isinstance(expr, Literal)


def _literal_value(expr: Expr) -> Any:
    if not isinstance(expr, Literal):
        raise ValueError(f"Expected literal, got {type(expr)!r}")
    return expr.value


def _prop_path(expr: Expr) -> str:
    """
    Extract an EDM-style property path (TitleCase segments with '/')
    from an RGQL expression.
    """
    if isinstance(expr, Identifier):
        return expr.name

    if isinstance(expr, MemberAccess):
        segments: List[str] = []
        cur: Expr = expr
        while isinstance(cur, MemberAccess):
            segments.append(cur.member)
            cur = cur.base
        if isinstance(cur, Identifier):
            segments.append(cur.name)
        segments.reverse()
        return "/".join(segments)

    raise ValueError(f"Expected property path, got {type(expr)!r}")


def _prop_path_to_column(prop_path: str) -> str:
    """
    Map an EDM property path in TitleCase to a snake_case column name.

    Simple rule for now:
        "UserId"         -> "user_id"
        "IsActive"       -> "is_active"
        "Address/City"   -> "address_city"  (segments joined with '_')

    Adjust this if you ever support real complex types / joins.
    """
    segments = prop_path.split("/")
    snake_segments = [title_to_snake(seg) for seg in segments]
    return "_".join(snake_segments)


@dataclass
class RGQLToRelationalAdapter:
    """
    Translate RGQLQueryOptions into FilterGroup/OrderBy/limit/offset.

    This lives on the backend side; RGQL itself does not import it.
    """

    # Optional customization hooks later, e.g. per-entity allowed props.
    allowed_properties: Sequence[str] = field(default_factory=list)

    def build_relational_query(
        self,
        opts: RGQLQueryOptions,
        *,
        path_planner: PathPlanner | None = None,
    ) -> Tuple[Sequence[FilterGroup], Sequence[OrderClause], int | None, int | None]:
        """
        Convert RGQLQueryOptions into (filter_groups, order_by, limit, offset).
        """
        filter_groups: List[FilterGroup] = []

        if opts.filter is not None:
            filter_groups = self._filter_to_groups(
                opts.filter,
                path_planner=path_planner,
            )

        order_by = self._orderby_to_order_by(
            opts.orderby or [],
            path_planner=path_planner,
        )
        limit = opts.top
        offset = opts.skip

        return filter_groups, order_by, limit, offset

    # ------------------------------------------------------------------ #
    # Filters: RGQL boolean expr -> DNF -> FilterGroup sequence
    # ------------------------------------------------------------------ #

    def _filter_to_groups(
        self,
        expr: Expr,
        *,
        path_planner: PathPlanner | None = None,
    ) -> List[FilterGroup]:
        groups: List[FilterGroup] = []

        dnf_clauses = to_dnf_clauses(expr)
        for clause in dnf_clauses:
            where: Dict[str, Any] = {}
            text_filters: List[TextFilter] = []
            scalar_filters: List[ScalarFilter] = []
            related_text_filters: List[RelatedTextFilter] = []
            related_scalar_filters: List[RelatedScalarFilter] = []

            for atom in clause:
                self._add_atom(
                    atom,
                    where,
                    text_filters,
                    scalar_filters,
                    related_text_filters,
                    related_scalar_filters,
                    path_planner=path_planner,
                )

            groups.append(
                FilterGroup(
                    where=where,
                    text_filters=text_filters,
                    scalar_filters=scalar_filters,
                    related_text_filters=related_text_filters,
                    related_scalar_filters=related_scalar_filters,
                )
            )

        return groups

    def _add_atom(
        self,
        expr: Expr,
        where: Dict[str, Any],
        text_filters: List[TextFilter],
        scalar_filters: List[ScalarFilter],
        related_text_filters: List[RelatedTextFilter] | None = None,
        related_scalar_filters: List[RelatedScalarFilter] | None = None,
        *,
        path_planner: PathPlanner | None = None,
    ) -> None:
        """
        Map a single atomic RGQL expression into predicates on one column.

        Supported patterns (initial set):
            Name eq 'Bob'
            Age  gt  18
            Price in [10, 20, 30]
            contains(Name, 'smith')
            startswith(Code, 'ABC')
            endswith(Sku, 'xyz')
        """
        if isinstance(expr, UnaryOp) and expr.op == "not":
            # You can implement NOT later via De Morgan normalization.
            raise ValueError("NOT filters are not supported yet in RGQL adapter")

        if related_text_filters is None:
            related_text_filters = []
        if related_scalar_filters is None:
            related_scalar_filters = []

        if isinstance(expr, BinaryOp):
            op = expr.op

            if op in {"eq", "ne", "gt", "ge", "lt", "le", "in"}:
                prop_path = _prop_path(expr.left)
                path_plan = path_planner(prop_path) if path_planner else None
                col = _prop_path_to_column(prop_path)

                rhs = expr.right
                if not _is_literal(rhs):
                    raise ValueError(
                        f"Only literal RHS is supported in filters, got {type(rhs)!r}"
                    )
                value = _literal_value(rhs)

                if path_plan is None:
                    if op == "eq":
                        if col in where and where[col] != value:
                            raise ValueError(
                                f"Conflicting equality predicates for column {col!r}"
                            )
                        where[col] = value
                    elif op == "ne":
                        scalar_filters.append(
                            ScalarFilter(field=col, op=ScalarFilterOp.NE, value=value)
                        )
                    elif op == "gt":
                        scalar_filters.append(
                            ScalarFilter(field=col, op=ScalarFilterOp.GT, value=value)
                        )
                    elif op == "ge":
                        scalar_filters.append(
                            ScalarFilter(field=col, op=ScalarFilterOp.GTE, value=value)
                        )
                    elif op == "lt":
                        scalar_filters.append(
                            ScalarFilter(field=col, op=ScalarFilterOp.LT, value=value)
                        )
                    elif op == "le":
                        scalar_filters.append(
                            ScalarFilter(field=col, op=ScalarFilterOp.LTE, value=value)
                        )
                    else:
                        # Remaining supported operator at this point is "in".
                        if not isinstance(value, (list, tuple)):
                            raise ValueError(
                                "IN operator expects a collection literal on RHS"
                            )
                        scalar_filters.append(
                            ScalarFilter(
                                field=col,
                                op=ScalarFilterOp.IN,
                                value=list(value),
                            )
                        )
                    return

                hops, terminal_col = path_plan

                if op == "in" and not isinstance(value, (list, tuple)):
                    raise ValueError("IN operator expects a collection literal on RHS")

                op_map = {
                    "eq": ScalarFilterOp.EQ,
                    "ne": ScalarFilterOp.NE,
                    "gt": ScalarFilterOp.GT,
                    "ge": ScalarFilterOp.GTE,
                    "lt": ScalarFilterOp.LT,
                    "le": ScalarFilterOp.LTE,
                    "in": ScalarFilterOp.IN,
                }
                related_scalar_filters.append(
                    RelatedScalarFilter(
                        path_hops=list(hops),
                        field=terminal_col,
                        op=op_map[op],
                        value=list(value) if op == "in" else value,
                    )
                )
                return

            if path_planner is not None:
                prop_path = _try_prop_path(expr.left)
                if prop_path is not None and path_planner(prop_path) is not None:
                    raise ValueError(
                        f"Nested navigation paths are not supported for operator {op!r}."
                    )

        if isinstance(expr, FunctionCall):
            name = expr.name.lower()
            args = expr.args

            if name in {"contains", "startswith", "endswith"} and len(args) == 2:
                prop_expr, value_expr = args
                prop_path = _prop_path(prop_expr)
                path_plan = path_planner(prop_path) if path_planner else None
                col = _prop_path_to_column(prop_path)

                if not _is_literal(value_expr):
                    raise ValueError(
                        f"{name}() expects a literal second argument; "
                        f"got {type(value_expr)!r}"
                    )
                value = _literal_value(value_expr)

                if name == "contains":
                    op = TextFilterOp.CONTAINS
                elif name == "startswith":
                    op = TextFilterOp.STARTSWITH
                else:
                    op = TextFilterOp.ENDSWITH

                if path_plan is None:
                    text_filters.append(
                        TextFilter(field=col, op=op, value=value, case_sensitive=False)
                    )
                else:
                    hops, terminal_col = path_plan
                    related_text_filters.append(
                        RelatedTextFilter(
                            path_hops=list(hops),
                            field=terminal_col,
                            op=op,
                            value=value,
                            case_sensitive=False,
                        )
                    )
                return

            if path_planner is not None and args:
                prop_path = _try_prop_path(args[0])
                if prop_path is not None and path_planner(prop_path) is not None:
                    raise ValueError(
                        f"Nested navigation paths are not supported for function "
                        f"{name}()."
                    )

        raise ValueError(f"Unsupported filter atom in RGQL adapter: {expr!r}")

    # ------------------------------------------------------------------ #
    # Order-by
    # ------------------------------------------------------------------ #

    def _orderby_to_order_by(
        self,
        items: Sequence[OrderByItem],
        *,
        path_planner: PathPlanner | None = None,
    ) -> Sequence[OrderClause]:
        result: List[OrderClause] = []

        for item in items:
            prop_path = _prop_path(item.expr)
            path_plan = path_planner(prop_path) if path_planner else None
            if path_plan is None:
                col = _prop_path_to_column(prop_path)
                result.append(
                    OrderBy(
                        field=col,
                        descending=item.direction == "desc",
                    )
                )
                continue

            hops, terminal_col = path_plan
            result.append(
                RelatedOrderBy(
                    path_hops=list(hops),
                    field=terminal_col,
                    descending=item.direction == "desc",
                    nulls_last=True,
                )
            )

        return result


def _try_prop_path(expr: Expr) -> str | None:
    try:
        return _prop_path(expr)
    except ValueError:
        return None
