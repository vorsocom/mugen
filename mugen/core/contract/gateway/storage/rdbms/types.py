"""Provides common types used by relational storage gateway contracts."""

__all__ = [
    "Record",
    "OrderBy",
    "TextFilterOp",
    "TextFilter",
]

from dataclasses import dataclass
from enum import auto, Enum
from typing import Any, MutableMapping

#: Represents a single database row as a mutable mapping of column-name -> value.
#:
#: Implementations typically return plain `dict` instances, but the contract only
#: requires that values behave like a mutable mapping. This keeps the interface flexible
#: while remaining easy to work with in user code.
Record = MutableMapping[str, Any]


class TextFilterOp(Enum):
    """Text filter operations for string fields."""

    CONTAINS = auto()
    STARTSWITH = auto()
    ENDSWITH = auto()


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
class TextFilter:
    """A text filter to be applied in addition to equality filters.

    Attributes
    ----------
    field:
        Logical column name to filter.
    op:
        TextFilterOp (contains/startswith/endswith).
    value:
        The value to match against (usually a string).
    """

    field: str
    op: TextFilterOp
    value: Any
