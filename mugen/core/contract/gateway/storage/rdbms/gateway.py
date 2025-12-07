"""Provides an abstract base class for creating relational database storage gateways."""

__all__ = ["IRelationalStorageGateway"]

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Mapping, Sequence

from mugen.core.contract.gateway.storage.rdbms.types import (
    OrderBy,
    Record,
    FilterGroup,
)
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork


class IRelationalStorageGateway(ABC):
    """An abstract base class for creating relational database storage gateways.

    Provides transactional access via IRelationalUnitOfWork, plus a few convenience
    helpers for common one-shot operations.
    """

    @asynccontextmanager
    @abstractmethod
    async def unit_of_work(self) -> AsyncIterator[IRelationalUnitOfWork]:
        """Yield a transactional unit of work.

        Implementation should:
            - open a connection/session.
            - start a transaction.
            - commit on a normal exit.
            - rollback on exception.

        Example
        -------
        uow: IRelationalUnitOfWork
        async with gateway.unit_of_work() as uow:
            await uow.insert("users", {"id": 1, "name": "Alice"})
            await uow.insert("profiles", {"user_id": 1, "bio": "..."})
        """

    async def insert_one(
        self,
        table: str,
        record: Mapping[str, Any],
    ) -> Record:
        """Insert a single row into `table` in its own transaction.

        This is a convenience wrapper around `unit_of_work()`
        + `IRelationalUnitOfWork.insert()` for the common case where you only need a
        single insert and do not need explicit transaction control.

        The exact semantics (e.g., whether the inserted row is fully populated with
        defaults / triggers) depend on the underlying implementation, but the intent is:
            - start the transaction.
            - insert the row.
            - commit.
            - return the inserted row as a mapping (usually a dict).

        For multiple related writes that must succeed or fail together, prefer using
        `unit_of_work()` directly.

        Parameters
        ----------
        table:
            Logical table name understood by the gateway implementation.
        record:
            Mapping of column-name -> value for the new row.

        Returns
        -------
        Record
            A mapping representing the inserted row (usually a `dict`). The concrete
            contents (e.g., whether defaults / triggers / database-generated values are
            populated) depend on the underlying implementation.

        """
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.insert(table, record)

    async def get_one(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> Record | None:
        """Fetch a single row in its own transaction.

        This is a convenience wrapper around `unit_of_work()` +
        `IRelationalUnitOfWork.get_one()`.

        Parameters
        ----------
        table:
            Logical table name understood by the gateway implementation.
        where:
            Mapping of column names -> values.

        Returns
        -------
        Record | None
            A mapping representing the row (usually a `dict`) if found, or `None` if no
            row exists.
        """
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.get_one(table, where)

    async def find_many(  # pylint: disable=too-many-arguments
        self,
        table: str,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderBy] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[Record]:
        """Fetch multiple rows in their own transaction.

        This is a convenience wrapper around `unit_of_work()` +
        `IRelationalUnitOfWork.find()`.

        Parameters
        ----------
        table:
            Logical table name understood by the gateway implementation.
        filter_groups:
            Optional sequence of :class:`FilterGroup` instances representing an
            OR-of-AND filter over the table's rows.
        order_by:
            Optional sequence of :class:`OrderBy` descriptors.
        limit:
            Optional maximum number of rows to return.
        offset:
            Optional number of rows to skip before returning results.
        """
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.find(
                table,
                filter_groups=filter_groups,
                order_by=order_by,
                limit=limit,
                offset=offset,
            )
