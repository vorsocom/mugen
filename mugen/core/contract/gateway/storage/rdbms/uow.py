"""Provides an abstract unit-of-work contract for relational storage gateways."""

__all__ = ["IRelationalUnitOfWork"]

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from mugen.core.contract.gateway.storage.rdbms.types import OrderBy, Record, TextFilter


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
    ) -> Record:
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
            A mapping representing the inserted row (usually a `dict`). The concrete
            contents (e.g., whether defaults / triggers / database-generated values
            are populated) depend on the underlying implementation.
        """

    @abstractmethod
    async def get_by_pk(
        self,
        table: str,
        pk: Mapping[str, Any],
    ) -> Record | None:
        """Fetch a single row by primary key (may be composite).

        Parameters
        ----------
        table:
            Logical table name understood by the unit-of-work implementation.
        pk:
            Mapping of primary-key column names to values. Composite keys are supported
            by passing multiple entries.

        Returns
        -------
        Record
            A mapping representing the row (usually a `dict`) if found, or `None` if no
            row exists for the given primary key.
        """

    @abstractmethod
    async def find(  # pylint: disable=too-many-arguments
        self,
        table: str,
        where: Mapping[str, Any] | None = None,
        *,
        text_filters: Sequence[TextFilter] | None = None,
        order_by: Sequence[OrderBy] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[Record]:
        """Run a simple select query.

        This method is intended for the common pattern of equality-based filtering and
        basic pagination.

        SELECT * FROM table WHERE col = value AND ... ORDER BY ... LIMIT/OFFSET.



        Parameters
        ----------
        table:
            Logical table name understood by the gateway implementation.
        where:
            Optional mapping of column-name -> value. All conditions are combined with
            logical AND, using equality comparison.
        order_by:
            Optional sequence of `OrderBy` descriptors, applied in order.
        limit:
            Optional maximum number of rows to return.
        offset:
            Optional number of rows to skip before returning results.

        Returns
        -------
        Sequence[Record]
            A sequence of row mappings (usually a list of dicts). The concrete type is
            not guaranteed, only that each element behaves like a mutable mapping (see
            `Record`).
        """

    @abstractmethod
    async def update(
        self,
        table: str,
        pk: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> Record | None:
        """Update a single row identified by `pk` with `changes`, optionally returning
        the updated row.

        Parameters
        ----------
        table:
            Logical table name understood by the unit-of-work implementation.
        pk:
            Mapping of primary-key column names to values. Composite keys are supported
            by passing multiple entries.
        changes:
            mapping of column-name -> new value. Implementations may treat an empty
            mapping as a no-op.
        returning:
            Whether to return the inserted row. If `True`, implementations should
            attempt to return a mapping containing the row values after insertion
            (including any database-generated values, where supported).

        Returns
        -------
        Record
            A mapping representing the row (usually a `dict`) if found, and `returning`
            is `True`, or `None` if no row exists for the given primary key or
            `returning` is `False`.
        """

    @abstractmethod
    async def delete(
        self,
        table: str,
        pk: Mapping[str, Any],
    ) -> None:
        """Delete a single row by primary key.

        Parameters
        ----------
        table:
            Logical table name understood by the unit-of-work implementation.
        pk:
            Mapping of primary-key column names to values. Composite keys are supported
            by passing multiple entries.

        Returns
        -------
        None
            This method does not return the deleted row. If callers need the row
            contents, they should fetch it via `get_by_pk` before invoking `delete`
            within the same unit-of-work.
        """
