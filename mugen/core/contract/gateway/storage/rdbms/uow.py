"""Provides an abstraction over a relational data store.

This interface exposes a very small, deliberately opinionated subset of
relational operations suitable for most read/write use-cases. It is
intentionally not a general-purpose query builder: callers are expected
to use equality filters, simple text filters and scalar comparison
filters, optionally combined with ordering and pagination.

Text filters are case-insensitive by default; callers can opt into
case-sensitive matching via the case_sensitive flag on TextFilter.

Filters are expressed as *sets of conjunctive groups*. Each group
represents a conjunction (logical AND) of simple predicates, and the
full set of groups is combined with logical OR. This corresponds to
Disjunctive Normal Form (DNF):

    (G1.predicates) OR (G2.predicates) OR ...

Implementations are free to map these groups to a single statement with
OR, or to multiple statements whose results are unioned.

Example
-------
A typical call that combines equality filters with text and scalar
filters might look like::

    async with uow_factory() as uow:
        rows = await uow.find(
            table="orders",
            filter_groups=[
                FilterGroup(
                    where={"status": "paid"},
                    text_filters=[
                        TextFilter(
                            field="customer_name",
                            op=TextFilterOp.CONTAINS,
                            value="smith",
                        ),
                    ],
                    scalar_filters=[
                        ScalarFilter(
                            field="total_cents",
                            op=ScalarFilterOp.GTE,
                            value=10_00,
                        ),
                        ScalarFilter(
                            field="created_at",
                            op=ScalarFilterOp.BETWEEN,
                            value=(start_dt, end_dt),
                        ),
                    ],
                )
            ],
            order_by=[OrderBy(field="created_at", descending=True)],
            limit=50,
        )

In this example:

* ``where`` enforces equality on the ``status`` column.
* ``text_filters`` applies a simple substring match on ``customer_name``.
* ``scalar_filters`` constrains the numeric ``total_cents`` column and
  limits ``created_at`` to a time range.
* All predicates within a group are combined with AND; groups are combined with OR.
"""

__all__ = ["IRelationalUnitOfWork"]

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from mugen.core.contract.gateway.storage.rdbms.types import (
    OrderBy,
    Record,
    FilterGroup,
)


class IRelationalUnitOfWork(ABC):
    """A transactional context for simple CRUD operations on flat tables.

    An `IRelationalUnitOfWork` represents a single database transaction. Implementations
    are responsible for executing statements against a concrete backend while conforming
    to this minimal, tool-agnostic interface.

    All methods operate on "logical" table names and rows represented as mapping objects
    (usually plain dicts).
    """

    @abstractmethod
    async def insert(
        self,
        table: str,
        record: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> Record | None:
        """Insert a single record into `table`.

        Parameters
        ----------
        table:
            Logical table name understood by the unit-of-work implementation.
        record:
            Mapping of column-name -> value for the new row.
        returning:
            Whether to return the inserted row. If `True`, implementations should
            attempt to return a mapping containing the row values after insertion
            (including any database-generated values, where supported).

        Returns
        -------
        Record
            A mapping representing the inserted row (usually a `dict`) if
            `returning` is True; otherwise `None`.
        """

    @abstractmethod
    async def get_one(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> Record | None:
        """Fetch a single row matching the given equality predicates.

        Parameters
        ----------
        table:
            Logical table name understood by the unit-of-work implementation.
        where:
            Mapping of column names to values.

        Returns
        -------
        Record | None
            A mapping representing the row (usually a `dict`) if exactly one row
            matches `where`, or `None` if no row matches.

        Raises
        ------
        MultipleResultsFound
            If more than one row matches `where`, depending on the concrete
            implementation.

        Notes
        -----
            - Callers are expected to pass predicates that uniquely identify a single
            row.
            - All keys in `where` are combined with logical AND.
        """

    @abstractmethod
    async def find(  # pylint: disable=too-many-arguments
        self,
        table: str,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderBy] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[Record]:
        """Run a select query with OR-of-AND filter semantics.

        This method is intended for the common pattern of applying simple
        predicates to a single logical table, optionally combined with ordering
        and pagination.

        Filters are supplied as a sequence of :class:`FilterGroup` instances.
        Each FilterGroup represents a conjunction (logical AND) of simple
        predicates. The full set of groups is combined with logical OR.

        Conceptually this corresponds to a statement of the form::

            SELECT * FROM table
            WHERE (G1.where AND G1.text AND G1.scalar)
               OR (G2.where AND G2.text AND G2.scalar)
               OR ...

        If ``filter_groups`` is None or empty, no filter is applied and all rows
        are eligible for selection.

        Parameters
        ----------
        table:
            Logical table name understood by the gateway implementation.
        filter_groups:
            Optional sequence of :class:`FilterGroup` instances. Each group
            describes a set of equality, text and scalar predicates that are
            combined with AND; the full set of groups is combined with OR.
        order_by:
            Optional sequence of :class:`OrderBy` descriptors, applied in order.
        limit:
            Optional maximum number of rows to return.
        offset:
            Optional number of rows to skip before returning results.

        Returns
        -------
        Sequence[Record]
            A sequence of row mappings (usually a list of dicts). The concrete
            type is not guaranteed, only that each element behaves like a
            mutable mapping (see :data:`Record`).
        """

    @abstractmethod
    async def update_one(
        self,
        table: str,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> Record | None:
        """Update a single row with `changes`, optionally returning the updated row.

        Parameters
        ----------
        table:
            Logical table name understood by the unit-of-work implementation.
        where:
            Mapping of column names to values.
        changes:
            Mapping of column-name -> new value. Implementations may treat an empty
            mapping as a no-op.
        returning:
            Whether to return the updated row. If `True`, implementations should
            attempt to return a mapping containing the row values after update
            (including any database-generated values, where supported).

        Returns
        -------
        Record | None
            A mapping representing the row (usually a `dict`) if found, and `returning`
            is `True`, or `None` if no row exists or `returning` is `False`.

        Raises
        ------
        MultipleResultsFound
            If more than one row matches `where`, depending on the concrete
            implementation.

        Notes
        -----
            - Callers are expected to pass predicates that uniquely identify a single
            row.
            - All keys in `where` are combined with logical AND.
        """

    @abstractmethod
    async def delete_one(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> None:
        """Delete a single row.

        Parameters
        ----------
        table:
            Logical table name understood by the unit-of-work implementation.
        where:
            Mapping of column names to values.

        Returns
        -------
        None
            This method does not return the deleted row. If callers need the row
            contents, they should fetch it before invoking `delete_one` within the same
            unit-of-work.

        Raises
        ------
        MultipleResultsFound
            If more than one row matches `where`, depending on the concrete
            implementation.

        Notes
        -----
            - Callers are expected to pass predicates that uniquely identify a single
            row.
            - All keys in `where` are combined with logical AND.
        """
