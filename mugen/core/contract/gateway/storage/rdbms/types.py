"""Provides common types used by relational storage gateway contracts."""

__all__ = [
    "Record",
    "OrderBy",
    "RelatedPathHop",
    "RelatedOrderBy",
    "OrderClause",
    "TextFilterOp",
    "TextFilter",
    "RelatedTextFilter",
    "ScalarFilterOp",
    "ScalarFilter",
    "RelatedScalarFilter",
    "FilterGroup",
    "RowVersionConflict",
]

from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Any, Mapping, MutableMapping, Sequence


class RowVersionConflict(RuntimeError):
    """Raised when an optimistic concurrency check based on ``row_version`` fails.

    This exception supports *optimistic concurrency control* for relational updates and
    deletes when tables expose an integer ``row_version`` column.

    Typical usage
    -------------
    Callers include the expected version in the equality predicates, e.g.::

        await gateway.update_one(
            "orders",
            where={"id": order_id, "row_version": expected_version},
            changes={"status": "paid"},
        )

    If the row exists but its current ``row_version`` differs from the provided expected
    value, the underlying implementation may raise this exception.

    Attributes
    ----------
    table:
        Logical table name.
    where:
        The WHERE predicate mapping supplied by the caller (often includes ``row_version``).
    """

    def __init__(self, table: str, where: Mapping[str, Any] | None = None) -> None:
        self.table = table
        self.where = dict(where) if where is not None else {}
        super().__init__(
            f"RowVersion conflict for table={table!r} where={self.where!r} "
            "(row was updated or deleted by another transaction)"
        )


#: Represents a single database row as a mutable mapping of column-name -> value.
#:
#: Implementations typically return plain `dict` instances, but the contract only
#: requires that values behave like a mutable mapping. This keeps the interface flexible
#: while remaining easy to work with in user code.
Record = MutableMapping[str, Any]


@dataclass
class OrderBy:
    """Simple ordering descriptor for a single column.

    Used by `IRelationalUnitOfWork.find()` and the gateway convenience methods to
    express SQL-style `ORDER BY` clauses in a tool-agnostic way.

    Attributes:
    field:
        Column name to order by. This should be the logical column name in the target
        table as understood by the gateway implementation.
    descending:
        Whether to sort in descending order. If `False` (the default), the sort is
        ascending.
    """

    field: str
    descending: bool = False


@dataclass(frozen=True)
class RelatedPathHop:
    """One navigation hop between two logical tables.

    Attributes
    ----------
    source_table:
        Logical source table name (for validation/debugging).
    source_field:
        Field on the source table used in the join predicate.
    target_table:
        Logical target table name.
    target_field:
        Field on the target table used in the join predicate.
    """

    source_table: str
    source_field: str
    target_table: str
    target_field: str


@dataclass(frozen=True)
class RelatedOrderBy:
    """Ordering descriptor for a field reached through related-table hops."""

    path_hops: Sequence[RelatedPathHop]
    field: str
    descending: bool = False
    nulls_last: bool = True


OrderClause = OrderBy | RelatedOrderBy


class ScalarFilterOp(Enum):
    """Operations for scalar comparison filters.

    These are used with :class:`ScalarFilter` to express non-text predicates in a
    backend-agnostic way. Implementations should map them onto the obvious SQL
    operators for scalar columns.

    Members
    -------
    EQ:
        Equality comparison.
    LT, LTE, GT, GTE:
        Strict/loose less-than and greater-than comparisons.
    NE:
        Inequality comparison.
    IN:
        Membership in a collection of values, similar to ``col IN (...)`` in SQL.
    BETWEEN:
        Inclusive range comparison, similar to ``col BETWEEN low AND high`` in SQL.
    """

    EQ = auto()
    LT = auto()
    LTE = auto()
    GT = auto()
    GTE = auto()
    NE = auto()
    IN = auto()
    BETWEEN = auto()


@dataclass(frozen=True)
class ScalarFilter:
    """Descriptor for a scalar comparison filter on a single column.

    Attributes
    ----------
    field:
        Logical column name to filter.
    op:
        Operation to apply, expressed as a :class:`ScalarFilterOp`.
    value:
        Value (or values) to compare against.

        The expected shape depends on ``op``:

        * ``EQ``, ``LT``, ``LTE``, ``GT``, ``GTE``, ``NE`` – a single scalar value.
        * ``IN`` – a non-string iterable of values.
        * ``BETWEEN`` – a pair ``(low, high)`` representing the inclusive bounds.
    """

    field: str
    op: ScalarFilterOp
    value: Any


@dataclass(frozen=True)
class RelatedScalarFilter:
    """Scalar comparison filter on a field reached through related-table hops."""

    path_hops: Sequence[RelatedPathHop]
    field: str
    op: ScalarFilterOp
    value: Any


class TextFilterOp(Enum):
    """Operations for simple text-based filters.

    These values are used with :class:`TextFilter` to express basic string
    matching semantics in a backend-agnostic way. Implementations typically
    map these onto ``LIKE``-style predicates for text columns.

    Members
    -------
    CONTAINS:
        Match rows where the field value contains the filter value as a
        substring.
    STARTSWITH:
        Match rows where the field value starts with the filter value.
    ENDSWITH:
        Match rows where the field value ends with the filter value.
    """

    CONTAINS = auto()
    STARTSWITH = auto()
    ENDSWITH = auto()


@dataclass(frozen=True)
class TextFilter:
    """A text filter to be applied in addition to equality filters.

    Text filters are intended for simple string search use-cases such as
    "contains", "starts with" and "ends with".

    By default, comparisons are **case-insensitive**. Implementations should
    normalise both the column value and the filter value (for example, by
    applying ``LOWER()``) when ``case_sensitive`` is ``False``. When
    ``case_sensitive`` is ``True``, implementations should perform a
    case-sensitive comparison if supported by the underlying backend.

    Attributes
    ----------
    field:
        Logical column name to filter.
    op:
        :class:`TextFilterOp` describing the kind of match to perform
        (contains/startswith/endswith).
    value:
        The value to match against (usually a string). Non-string values may
        be coerced to strings by implementations.
    case_sensitive:
        Whether the comparison should be case-sensitive. Defaults to
        ``False`` (case-insensitive).
    """

    field: str
    op: TextFilterOp
    value: Any
    case_sensitive: bool = False


@dataclass(frozen=True)
class RelatedTextFilter:
    """Text filter on a field reached through related-table hops."""

    path_hops: Sequence[RelatedPathHop]
    field: str
    op: TextFilterOp
    value: Any
    case_sensitive: bool = False


@dataclass
class FilterGroup:
    """Represents a conjunction (AND) of simple predicates on a single table.

    A ``FilterGroup`` collects the three existing predicate kinds:

    * ``where``         -- equality predicates (column == value)
    * ``text_filters``  -- :class:`TextFilter` instances (contains/startswith/endswith)
    * ``scalar_filters``-- :class:`ScalarFilter` instances (lt/lte/gt/gte/ne/in/between)

    All predicates within a single group are to be combined with logical AND.

    Higher-level APIs (such as :class:`IRelationalUnitOfWork`) are expected to
    accept *multiple* FilterGroup instances and combine them with OR, yielding
    an overall predicate of the form::

        (G1.where AND G1.text AND G1.scalar)
     OR (G2.where AND G2.text AND G2.scalar)
     OR ...
    """

    where: Mapping[str, Any] = field(default_factory=dict)
    text_filters: Sequence[TextFilter] = field(default_factory=list)
    scalar_filters: Sequence[ScalarFilter] = field(default_factory=list)
    related_text_filters: Sequence[RelatedTextFilter] = field(default_factory=list)
    related_scalar_filters: Sequence[RelatedScalarFilter] = field(default_factory=list)
