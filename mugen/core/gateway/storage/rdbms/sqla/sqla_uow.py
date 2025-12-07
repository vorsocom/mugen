"""Provides an SQLAlchemy-backed implementation of IRelationalUnitOfWork."""

__all__ = ["SQLAlchemyRelationalUnitOfWork"]

from collections.abc import Iterable
from typing import Any, Mapping, MutableMapping, Sequence

from sqlalchemy import (
    and_,
    or_,
    delete as sa_delete,
    false as sa_false,
    insert as sa_insert,
    select as sa_select,
    update as sa_update,
    Table,
    func,
)

from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession

from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    Record,
    TextFilter,
    TextFilterOp,
    ScalarFilter,
    ScalarFilterOp,
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
        record: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> Record | None:
        """See IRelationalUnitOfWork.insert for contract semantics."""
        tbl = self._get_table(table)
        stmt = sa_insert(tbl).values(**record)

        if returning:
            stmt = stmt.returning(tbl)

        result: Result = await self._session.execute(stmt)

        if not returning:
            return None

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
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderBy] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[Record]:
        tbl = self._get_table(table)
        stmt = sa_select(tbl)

        # Build the overall WHERE predicate from filter_groups
        if filter_groups:
            group_exprs = [
                self._predicates_for_group(tbl, group) for group in filter_groups
            ]
            # Drop empty groups (no predicates)
            group_exprs = [g for g in group_exprs if g is not None]

            if group_exprs:
                if len(group_exprs) == 1:
                    stmt = stmt.where(group_exprs[0])
                else:
                    stmt = stmt.where(or_(*group_exprs))

        # ORDER BY
        if order_by:
            order_clauses = []
            for ob in order_by:
                col = getattr(tbl.c, ob.field)
                order_clauses.append(col.desc() if ob.descending else col.asc())
            stmt = stmt.order_by(*order_clauses)

        # LIMIT / OFFSET
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)

        result = await self._session.execute(stmt)
        rows = [dict(row) for row in result.mappings()]
        return rows

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

    # pylint: disable=too-many-locals
    # pylint: disable=too-many-branches
    def _build_predicates(
        self,
        table: Table,
        where: Mapping[str, Any] | None = None,
        text_filters: Sequence[TextFilter] | None = None,
        scalar_filters: Sequence[ScalarFilter] | None = None,
    ) -> list:
        """Translate contract-level filter arguments into SQLAlchemy predicates.

        This is the single canonical implementation of:
        - equality predicates from ``where``,
        - text predicates from ``text_filters``, and
        - scalar predicates from ``scalar_filters``.

        All returned predicates are meant to be combined with AND by callers.
        """
        clauses: list = []

        # Equality predicates: col == value
        if where:
            for col_name, value in where.items():
                col = getattr(table.c, col_name)
                clauses.append(col == value)

        # Text filters
        if text_filters:
            for tf in text_filters:
                col = getattr(table.c, tf.field)

                if tf.case_sensitive:
                    col_expr = col
                    pattern_value = str(tf.value)
                else:
                    col_expr = func.lower(col)
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

        # Scalar filters (<, >, BETWEEN, IN, etc.)
        if scalar_filters:
            for sf in scalar_filters:
                col = getattr(table.c, sf.field)
                op = sf.op
                val = sf.value

                if op is ScalarFilterOp.LT:
                    clauses.append(col < val)
                elif op is ScalarFilterOp.LTE:
                    clauses.append(col <= val)
                elif op is ScalarFilterOp.GT:
                    clauses.append(col > val)
                elif op is ScalarFilterOp.GTE:
                    clauses.append(col >= val)
                elif op is ScalarFilterOp.NE:
                    clauses.append(col != val)
                elif op is ScalarFilterOp.IN:
                    # Defensive handling: require non-string iterable;
                    # treat empty iterable as a predicate that's always false.
                    if isinstance(val, str) or not isinstance(val, Iterable):
                        raise TypeError(
                            "ScalarFilterOp.IN value must be a non-string iterable; "
                            f"got {type(val)!r}"
                        )
                    seq = list(val)
                    if not seq:
                        clauses.append(sa_false())
                    else:
                        clauses.append(col.in_(seq))
                elif op is ScalarFilterOp.BETWEEN:
                    low, high = val
                    clauses.append(col.between(low, high))
                else:
                    raise ValueError(f"Unsupported ScalarFilterOp: {op!r}")

        return clauses

    def _predicates_for_group(self, table, group: FilterGroup):
        """Build a SQLAlchemy boolean expression for a single FilterGroup.

        All predicates in the group are combined with AND. If the group
        contains no predicates, returns None.
        """
        predicates = self._build_predicates(
            table=table,
            where=group.where,
            text_filters=group.text_filters,
            scalar_filters=group.scalar_filters,
        )

        if not predicates:
            return None

        return and_(*predicates)

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def _apply_where(
        self,
        table: Table,
        stmt,
        where: Mapping[str, Any] | None,
        text_filters: Sequence[TextFilter] | None = None,
        scalar_filters: Sequence[ScalarFilter] | None = None,
    ):
        """Apply contract-level filters to a SQLAlchemy statement.

        This is a thin wrapper that uses ``_build_predicates`` and attaches a
        single AND-combined WHERE clause to *stmt*. It exists primarily for
        simpler APIs (get/update/delete) that don't use FilterGroup directly.
        """
        clauses = self._build_predicates(
            table=table,
            where=where,
            text_filters=text_filters,
            scalar_filters=scalar_filters,
        )

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
