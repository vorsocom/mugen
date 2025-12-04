"""Provides an SQLAlchemy-backed implmentation of IRelationalUnitOfWork."""

__all__ = ["SQLAlchemyRelationalUnitOfWork"]

from typing import Any, Mapping, MutableMapping, Sequence

from sqlalchemy import (
    and_,
    asc,
    desc,
    delete as sa_delete,
    insert as sa_insert,
    select as sa_select,
    update as sa_update,
    Table,
    func,
)

from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession

from mugen.core.contract.gateway.storage.rdbms.types import (
    OrderBy,
    Record,
    TextFilter,
    TextFilterOp,
)
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork

TableRegistry = MutableMapping[str, Table]


class SQLAlchemyRelationalUnitOfWork(IRelationalUnitOfWork):
    """An SQLAlchemy-backed implementation of IRelationalUnitOfWork.

    This unit of work wraps an SQLAlchemy `AsyncSession` and a registry SQLAlchemy
    `Table` objects. It translates the contract methods into SQLAlchemy Core statements
    and executes them within a single transaction.

    Parameters
    ----------
    session:
        The active SQLAlchemy `AsyncSession` bound to a transaction.
    tables:
        Mapping of logical table name -> SQLAlchemy `Table` object. The logical names
        must match those used by higher-level code and by the configured relational
        gateway.
    """

    def __init__(self, session: AsyncSession, tables: TableRegistry) -> None:
        self._session = session
        self._tables = tables

    async def insert(
        self,
        table: str,
        record: Record,
        *,
        returning: bool = True,
    ) -> Record:
        """See IRelationalUnitOfWork.insert for contract semantics."""
        tbl = self._get_table(table)
        stmt = sa_insert(tbl).values(**record)

        if returning:
            stmt = stmt.returning(tbl)

        result: Result = await self._session.execute(stmt)

        if not returning:
            # Minimal placeholder. Callers who pass returning=False should not rely on
            # the returned contents.
            return {}

        row = result.mappings().one()
        return dict(row)

    async def get_by_pk(
        self,
        table: str,
        pk: Mapping[str, Any],
    ) -> Record | None:
        """See IRelationalUnitOfWork.get_by_pk for contract semantics."""
        tbl = self._get_table(table)
        stmt = sa_select(tbl)
        stmt = self._apply_where(tbl, stmt, pk)

        result: Result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

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
        """See IRelationalUnitOfWork.find for contract semantics."""
        tbl = self._get_table(table)
        stmt = sa_select(tbl)
        stmt = self._apply_where(tbl, stmt, where, text_filters)

        if order_by:
            order_exprs = []
            for ob in order_by:
                col = tbl.c[ob.field]
                order_exprs.append(desc(col) if ob.descending else asc(col))
            stmt = stmt.order_by(*order_exprs)

        if limit is not None:
            stmt = stmt.limit(limit)

        if offset is not None:
            stmt = stmt.offset(offset)

        result: Result = await self._session.execute(stmt)
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def update(
        self,
        table: str,
        pk: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> Record | None:
        """See IRelationalUnitOfWork.update for contract semantics."""
        if not changes:
            # No changes. Obey contract semantics by just refetching when requested.
            return await self.get_by_pk(table, pk) if returning else None

        tbl = self._get_table(table)
        stmt = sa_update(tbl).values(**changes)
        stmt = self._apply_where(tbl, stmt, pk)

        if returning:
            stmt = stmt.returning(tbl)

        result: Result = await self._session.execute(stmt)

        if not returning:
            return None

        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    async def delete(
        self,
        table: str,
        pk: Mapping[str, Any],
    ) -> None:
        """See IRelationalUnitOfWork.delete for contract semantics."""
        tbl = self._get_table(table)
        stmt = sa_delete(tbl)
        stmt = self._apply_where(tbl, stmt, pk)
        await self._session.execute(stmt)

    def _apply_where(
        self,
        table: Table,
        stmt,
        where: Mapping[str, Any] | None,
        text_filters: Sequence[TextFilter] | None = None,
    ):
        """Apply equality-based WHERE conditions to a SQLAlchemy statement."""
        clauses = []

        # Equality filters
        if where:
            clauses.extend(table.c[col] == value for col, value in where.items())

        # Text filters: contains/startswith/endswith
        if text_filters:
            for tf in text_filters:
                col = table.c[tf.field]

                # Use case-insensitive matching for now.
                col_expr = func.lower(col)
                if isinstance(tf.value, str):
                    pattern_value = tf.value.lower()
                else:
                    # Safest fallback: coerce to string
                    pattern_value = str(tf.value).lower()

                if tf.op is TextFilterOp.CONTAINS:
                    pattern = f"%{pattern_value}%"
                elif tf.op is TextFilterOp.STARTSWITH:
                    pattern = f"{pattern_value}%"
                elif tf.op is TextFilterOp.ENDSWITH:
                    pattern = f"%{pattern_value}"
                else:
                    raise ValueError(f"Unsupported TextFilterOp: {tf.op!r}")

                clauses.append(col_expr.like(pattern))

        if not clauses:
            return stmt

        return stmt.where(and_(*clauses))

    def _get_table(self, name: str) -> Table:
        """Resolve a logical table name to its SQLAlchemy Table object."""
        try:
            return self._tables[name]
        except KeyError as exc:
            raise KeyError(
                f"Unknown table name {name!r} in SQLAlchemyRelationalUnitOfWork"
            ) from exc
