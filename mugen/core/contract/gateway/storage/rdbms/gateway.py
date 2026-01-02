"""Provides an abstract base class for creating relational database storage gateways."""

__all__ = ["IRelationalStorageGateway"]

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Mapping, Sequence

from mugen.core.contract.gateway.storage.rdbms.types import (  # pylint: disable=unused-import
    OrderBy,
    Record,
    FilterGroup,
    RowVersionConflict,
)
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork


class IRelationalStorageGateway(ABC):
    """An abstract base class for creating relational database storage gateways.

    Provides transactional access via IRelationalUnitOfWork, plus convenience helpers
    for common one-shot operations.

    Optimistic concurrency via ``row_version``
    -----------------------------------------
    If tables expose a ``row_version`` column, callers can perform optimistic concurrency
    checks for updates and deletes by including an expected version in the ``where``
    mapping, e.g.::

        await gateway.update_one(
            "orders",
            where={"id": order_id, "row_version": expected_version},
            changes={"status": "paid"},
        )

    Implementations typically translate this into a statement whose WHERE clause includes
    ``row_version == expected_version``. If the statement affects zero rows and the base
    row still exists, a :class:`RowVersionConflict` may be raised.
    """

    @asynccontextmanager
    @abstractmethod
    async def unit_of_work(self) -> AsyncIterator[IRelationalUnitOfWork]:
        """Yield a transactional unit of work.

        Implementation should:
            - open a connection/session
            - start a transaction
            - commit on a normal exit
            - rollback on exception
        """

    async def count_many(
        self,
        table: str,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
    ) -> int:
        """Count rows in `table` in their own transaction."""
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.count(table, filter_groups=filter_groups)

    async def insert_one(
        self,
        table: str,
        record: Mapping[str, Any],
    ) -> Record:
        """Insert a single row into `table` in its own transaction."""
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.insert(table, record)

    async def get_one(
        self,
        table: str,
        where: Mapping[str, Any],
        *,
        columns: Sequence[str] | None = None,
    ) -> Record | None:
        """Fetch a single row in its own transaction."""
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.get_one(table, where, columns=columns)

    async def find_many(  # pylint: disable=too-many-arguments
        self,
        table: str,
        *,
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderBy] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[Record]:
        """Fetch multiple rows in their own transaction."""
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.find(
                table,
                columns=columns,
                filter_groups=filter_groups,
                order_by=order_by,
                limit=limit,
                offset=offset,
            )

    async def find_many_partitioned_by_fk(  # pylint: disable=too-many-arguments
        self,
        table: str,
        *,
        fk_field: str,
        fk_values: Sequence[Any],
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderBy] | None = None,
        per_fk_limit: int | None = None,
        per_fk_offset: int | None = None,
    ) -> Sequence[Record]:
        """Fetch multiple rows in their own transaction, with partitioning by fk."""
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.find_partitioned_by_fk(
                table,
                fk_field=fk_field,
                fk_values=fk_values,
                columns=columns,
                filter_groups=filter_groups,
                order_by=order_by,
                per_fk_limit=per_fk_limit,
                per_fk_offset=per_fk_offset,
            )

    async def update_one(
        self,
        table: str,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> Record | None:
        """Update a single row in `table` in its own transaction.

        If `where` includes a ``row_version`` key, the underlying unit-of-work may treat
        it as an optimistic concurrency token.

        Returns
        -------
        Record | None
            Updated row mapping, or None if no row matched `where`.

        Raises
        ------
        RowVersionConflict
            If an optimistic concurrency check fails (most commonly when ``where``
            includes ``row_version`` and the UPDATE affects zero rows).
        """
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.update_one(table, where, changes, returning=True)

    async def delete_one(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> Record | None:
        """Delete a single row from `table` in its own transaction.

        If `where` includes a ``row_version`` key, the underlying unit-of-work may treat
        it as an optimistic concurrency token.

        Returns
        -------
        Record | None
            The deleted row mapping, or None if no row matched `where`.

        Raises
        ------
        RowVersionConflict
            If an optimistic concurrency check fails (most commonly when ``where``
            includes ``row_version`` and the DELETE affects zero rows while the base row
            still exists).
        """
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            return await uow.delete_one(table, where)

    async def delete_many(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> None:
        """Delete multiple rows from `table` in its own transaction."""
        uow: IRelationalUnitOfWork
        async with self.unit_of_work() as uow:
            await uow.delete_many(table, where)
