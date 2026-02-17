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
    Select,
    Table,
    func as sa_func,
)

from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession

from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderClause,
    OrderBy,
    RelatedOrderBy,
    RelatedPathHop,
    RelatedScalarFilter,
    RelatedTextFilter,
    Record,
    ScalarFilter,
    ScalarFilterOp,
    TextFilter,
    TextFilterOp,
)
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork

TableRegistry = MutableMapping[str, Table]


class SQLAlchemyRelationalUnitOfWork(IRelationalUnitOfWork):
    """An SQLAlchemy-backed implementation of IRelationalUnitOfWork.

    This unit of work wraps an SQLAlchemy `AsyncSession` and a registry of SQLAlchemy
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

    Optimistic concurrency via row_version
    --------------------------------------
    If a table has a ``row_version`` column and callers include ``row_version`` in the
    `where` mapping for update/delete, this implementation enforces optimistic
    concurrency:

    - UPDATE/DELETE includes ``row_version == expected`` in its WHERE clause.
    - UPDATE automatically increments the stored row_version on success (unless the
      caller explicitly sets row_version in `changes`).
    - If no row is affected and the base identity row exists (same `where` without
      row_version), a RowVersionConflict is raised.
    """

    def __init__(self, session: AsyncSession, tables: TableRegistry) -> None:
        self._session = session
        self._tables = tables

    async def count(
        self,
        table: str,
        *,
        filter_groups: Sequence[FilterGroup] | None = None,
    ) -> int:
        """Count records that match the given filter groups."""
        tbl = self._get_table(table)
        stmt = sa_select(sa_func.count()).select_from(  # pylint: disable=not-callable
            tbl
        )

        if filter_groups:
            group_exprs = [
                self._predicates_for_group(tbl, group) for group in filter_groups
            ]
            group_exprs = [g for g in group_exprs if g is not None]

            if group_exprs:
                if len(group_exprs) == 1:
                    stmt = stmt.where(group_exprs[0])
                else:
                    stmt = stmt.where(or_(*group_exprs))

        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

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

    async def get_one(
        self,
        table: str,
        where: Mapping[str, Any],
        *,
        columns: Sequence[str] | None = None,
    ) -> Record | None:
        """See IRelationalUnitOfWork.get_one for contract semantics."""
        tbl = self._get_table(table)

        if columns:
            try:
                sel_cols = [getattr(tbl.c, col_name) for col_name in columns]
            except AttributeError as exc:
                raise ValueError(
                    f"Unknown column in 'columns' argument for table {table!r}: {exc}"
                ) from exc
            stmt = sa_select(*sel_cols)
        else:
            stmt = sa_select(tbl)

        stmt = self._apply_where(tbl, stmt, where)

        result: Result = await self._session.execute(stmt)
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-locals
    # pylint: disable=too-many-branches
    async def find(
        self,
        table: str,
        *,
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderClause] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[Record]:
        """See IRelationalUnitOfWork.find for contract semantics."""
        tbl = self._get_table(table)

        if columns:
            try:
                sel_cols = [getattr(tbl.c, col_name) for col_name in columns]
            except AttributeError as exc:
                raise ValueError(
                    f"Unknown column in 'columns' argument for table {table!r}: {exc}"
                ) from exc
            stmt = sa_select(*sel_cols)
        else:
            stmt = sa_select(tbl)

        # Build the overall WHERE predicate from filter_groups
        if filter_groups:
            group_exprs = [self._predicates_for_group(tbl, g) for g in filter_groups]
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
                if isinstance(ob, RelatedOrderBy):
                    order_clauses.append(self._related_order_clause(tbl, ob))
                    continue
                col = getattr(tbl.c, ob.field)
                order_clauses.append(col.desc() if ob.descending else col.asc())
            stmt = stmt.order_by(*order_clauses)

        # LIMIT / OFFSET
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)

        result = await self._session.execute(stmt)
        return [dict(row) for row in result.mappings()]

    async def find_partitioned_by_fk(
        self,
        table: str,
        *,
        fk_field: str,
        fk_values: Sequence[Any],
        columns: Sequence[str] | None = None,
        filter_groups: Sequence[FilterGroup] | None = None,
        order_by: Sequence[OrderClause] | None = None,
        per_fk_limit: int | None = None,
        per_fk_offset: int | None = None,
        tie_breaker_field: str = "id",
    ) -> Sequence[Record]:
        """See IRelationalUnitOfWork.find_partitioned_by_fk for contract semantics."""
        if not fk_values:
            return []

        # Normalize / dedupe FK values to reduce IN(...) size and improve plan stability.
        # Preserve order when values are hashable; fall back to raw list if not.
        try:
            fk_values_list = list(dict.fromkeys(fk_values))
        except TypeError:
            fk_values_list = list(fk_values)

        if not fk_values_list:
            return []

        tbl = self._get_table(table)

        offset = int(per_fk_offset or 0)
        if offset < 0:
            raise ValueError("per_fk_offset must be >= 0")

        limit = per_fk_limit
        if limit is not None and limit < 0:
            raise ValueError("per_fk_limit must be >= 0")

        # Build base SELECT projection.
        projected_cols: list[Any] = []
        if columns:
            try:
                col_names = list(dict.fromkeys([*columns, fk_field]))
                projected_cols = [getattr(tbl.c, c) for c in col_names]
            except AttributeError as exc:
                raise ValueError(
                    f"Unknown column in `columns` argument for table {table!r}: {exc}"
                ) from exc

        fk_col = getattr(tbl.c, fk_field)

        # --- base statement ---
        base: Select
        if projected_cols:
            base = sa_select(*projected_cols).select_from(tbl)
        else:
            base = sa_select(tbl).select_from(tbl)

        # Apply fk predicate (use equality when there is a single FK for simpler plans).
        if len(fk_values_list) == 1:
            base = base.where(fk_col == fk_values_list[0])
        else:
            base = base.where(fk_col.in_(fk_values_list))

        # Apply filter_groups exactly like find(): OR across groups.
        if filter_groups:
            group_exprs = [self._predicates_for_group(tbl, g) for g in filter_groups]
            group_exprs = [g for g in group_exprs if g is not None]
            if group_exprs:
                if len(group_exprs) == 1:
                    base = base.where(group_exprs[0])
                else:
                    base = base.where(or_(*group_exprs))

        # --- order expressions for the window ---
        order_exprs = []
        order_fields: set[str] = set()
        if order_by:
            for ob in order_by:
                if isinstance(ob, RelatedOrderBy):
                    order_exprs.append(self._related_order_clause(tbl, ob))
                else:
                    col = getattr(tbl.c, ob.field)
                    order_exprs.append(col.desc() if ob.descending else col.asc())
                    order_fields.add(ob.field)

        # Always add a deterministic tie-breaker for stable row_number ordering.
        if tie_breaker_field in tbl.c and tie_breaker_field not in order_fields:
            order_exprs.append(getattr(tbl.c, tie_breaker_field).asc())

        # row_number() over (partition by fk ORDER BY ...)
        rn = (
            sa_func.row_number()
            .over(
                partition_by=fk_col,
                order_by=order_exprs if order_exprs else None,
            )
            .label("__rn")
        )

        ranked = base.add_columns(rn).subquery("ranked")

        # Outer query: select original projected columns (not rn), filter by rn range.
        # For "tbl" selection, ranked.c will contain all table columns plus __rn.
        if columns:
            out_cols = [ranked.c[c] for c in [*dict.fromkeys([*columns, fk_field])]]
        else:
            # selecting tbl means ranked.c has all columns; easiest is to select all
            # ranked columns except rn.
            out_cols = [c for c in ranked.c if c.key != "__rn"]

        stmt = sa_select(*out_cols)

        if limit is not None:
            low = offset + 1
            high = offset + limit
            stmt = stmt.where(ranked.c["__rn"].between(low, high))
        elif offset:
            stmt = stmt.where(ranked.c["__rn"] >= (offset + 1))

        result = await self._session.execute(stmt)
        return [dict(row) for row in result.mappings()]

    async def update_one(
        self,
        table: str,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> Record | None:
        """See IRelationalUnitOfWork.update_one for contract semantics."""
        if not changes:
            return await self.get_one(table, where) if returning else None

        tbl = self._get_table(table)

        values: dict[str, Any] = dict(changes)

        # If the table supports row_version and caller isn't explicitly setting it,
        # increment it on successful update.
        if "row_version" in tbl.c and "row_version" not in values:
            values["row_version"] = tbl.c.row_version + 1

        stmt = sa_update(tbl).values(**values)
        stmt = self._apply_where(tbl, stmt, where)

        # If we want the updated row, RETURNING is the cleanest way to both fetch it
        # and detect "no rows affected" reliably.
        if returning:
            stmt = stmt.returning(tbl)

        result: Result = await self._session.execute(stmt)

        if not returning:
            # If optimistic concurrency is requested (row_version in where) and no rows
            # were updated, decide whether to raise RowVersionConflict vs "not found".
            if "row_version" in where:
                if (result.rowcount or 0) == 0:
                    await self._raise_if_row_version_conflict(table, tbl, where)
            return None

        row = result.mappings().one_or_none()
        if row is not None:
            return dict(row)

        # No row updated.
        if "row_version" in where:
            await self._raise_if_row_version_conflict(table, tbl, where)
        return None

    async def delete_one(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> Record | None:
        """See IRelationalUnitOfWork.delete_one for contract semantics."""
        tbl = self._get_table(table)

        # Use RETURNING so we can reliably detect "no rows deleted" without relying
        # purely on rowcount.
        stmt = sa_delete(tbl).returning(tbl)
        stmt = self._apply_where(tbl, stmt, where)

        result: Result = await self._session.execute(stmt)
        deleted = result.mappings().one_or_none()

        if deleted is not None:
            return dict(deleted)

        # No row deleted.
        if "row_version" in where:
            await self._raise_if_row_version_conflict(table, tbl, where)

    async def delete_many(
        self,
        table: str,
        where: Mapping[str, Any],
    ) -> None:
        """See IRelationalUnitOfWork.delete_many for contract semantics."""
        tbl = self._get_table(table)
        stmt = sa_delete(tbl)
        stmt = self._apply_where(tbl, stmt, where)
        await self._session.execute(stmt)

    # ----------------------------
    # Concurrency helpers
    # ----------------------------

    def _where_without_row_version(self, where: Mapping[str, Any]) -> dict[str, Any]:
        """Return a copy of `where` with any row_version predicate removed."""
        base = dict(where)
        base.pop("row_version", None)
        return base

    async def _raise_if_row_version_conflict(
        self,
        table: str,
        tbl: Table,
        where: Mapping[str, Any],
    ) -> None:
        """Raise RowVersionConflict if the row exists but the row_version predicate failed.

        If the base row (identified by predicates excluding row_version) does not exist,
        treat the condition as "not found" and do not raise.
        """
        # If we cannot form an identity predicate, we cannot distinguish "not found"
        # from "conflict". In that case, treat as conflict when the caller requested it.
        identity_where = self._where_without_row_version(where)
        if not identity_where:
            raise RowVersionConflict(table, where)

        stmt = sa_select(tbl.c.row_version).select_from(tbl)
        stmt = self._apply_where(tbl, stmt, identity_where)
        stmt = stmt.limit(1)

        res = await self._session.execute(stmt)
        existing_version = res.scalar_one_or_none()

        if existing_version is None:
            # Row doesn't exist -> no conflict, it's "not found".
            return

        # Row exists but (id + row_version) predicate matched nothing -> conflict.
        raise RowVersionConflict(table, where)

    # ----------------------------
    # Predicate building
    # ----------------------------

    # pylint: disable=too-many-locals
    # pylint: disable=too-many-branches
    def _build_predicates(
        self,
        table: Table,
        where: Mapping[str, Any] | None = None,
        text_filters: Sequence[TextFilter] | None = None,
        scalar_filters: Sequence[ScalarFilter] | None = None,
        related_text_filters: Sequence[RelatedTextFilter] | None = None,
        related_scalar_filters: Sequence[RelatedScalarFilter] | None = None,
    ) -> list[Any]:
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
                    col_expr = sa_func.lower(col)
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
                clauses.append(
                    self._scalar_clause_for_op(
                        col=col,
                        op=sf.op,
                        val=sf.value,
                    )
                )

        if related_text_filters:
            for idx, rtf in enumerate(related_text_filters):
                from_clause, correlation_clause, terminal_alias = self._resolve_related_path(
                    table=table,
                    path_hops=rtf.path_hops,
                    alias_prefix=f"rtf_{idx}",
                )
                col = getattr(terminal_alias.c, rtf.field)

                if rtf.case_sensitive:
                    col_expr = col
                    pattern_value = str(rtf.value)
                else:
                    col_expr = sa_func.lower(col)
                    pattern_value = str(rtf.value).lower()

                if rtf.op is TextFilterOp.CONTAINS:
                    pattern = f"%{pattern_value}%"
                elif rtf.op is TextFilterOp.STARTSWITH:
                    pattern = f"{pattern_value}%"
                elif rtf.op is TextFilterOp.ENDSWITH:
                    pattern = f"%{pattern_value}"
                else:
                    raise ValueError(f"Unsupported TextFilterOp: {rtf.op!r}")

                terminal_predicate = col_expr.like(pattern)
                clauses.append(
                    self._related_exists_clause(
                        from_clause=from_clause,
                        correlation_clause=correlation_clause,
                        terminal_predicate=terminal_predicate,
                    )
                )

        if related_scalar_filters:
            for idx, rsf in enumerate(related_scalar_filters):
                from_clause, correlation_clause, terminal_alias = self._resolve_related_path(
                    table=table,
                    path_hops=rsf.path_hops,
                    alias_prefix=f"rsf_{idx}",
                )
                col = getattr(terminal_alias.c, rsf.field)
                terminal_predicate = self._scalar_clause_for_op(
                    col=col,
                    op=rsf.op,
                    val=rsf.value,
                )
                clauses.append(
                    self._related_exists_clause(
                        from_clause=from_clause,
                        correlation_clause=correlation_clause,
                        terminal_predicate=terminal_predicate,
                    )
                )

        return clauses

    def _scalar_clause_for_op(self, col: Any, op: ScalarFilterOp, val: Any) -> Any:
        if op is ScalarFilterOp.EQ:
            return col == val
        if op is ScalarFilterOp.LT:
            return col < val
        if op is ScalarFilterOp.LTE:
            return col <= val
        if op is ScalarFilterOp.GT:
            return col > val
        if op is ScalarFilterOp.GTE:
            return col >= val
        if op is ScalarFilterOp.NE:
            return col != val
        if op is ScalarFilterOp.IN:
            if isinstance(val, str) or not isinstance(val, Iterable):
                raise TypeError(
                    "ScalarFilterOp.IN value must be a non-string iterable; "
                    f"got {type(val)!r}"
                )
            seq = list(val)
            if not seq:
                return sa_false()
            return col.in_(seq)
        if op is ScalarFilterOp.BETWEEN:
            low, high = val
            return col.between(low, high)
        raise ValueError(f"Unsupported ScalarFilterOp: {op!r}")

    def _resolve_related_path(
        self,
        *,
        table: Table,
        path_hops: Sequence[RelatedPathHop],
        alias_prefix: str,
    ) -> tuple[Any, Any, Any]:
        if not path_hops:
            raise ValueError("Related filters/ordering require at least one path hop.")

        current_alias = table
        target_aliases: list[Any] = []
        join_clauses: list[Any] = []
        correlation_clause = None

        for idx, hop in enumerate(path_hops):
            if idx == 0 and hop.source_table and hop.source_table != table.name:
                raise ValueError(
                    "Related path source table mismatch: expected "
                    f"{table.name!r}, got {hop.source_table!r}."
                )

            target_table = self._get_table(hop.target_table)
            target_alias = target_table.alias(f"{alias_prefix}_h{idx}")

            try:
                source_col = getattr(current_alias.c, hop.source_field)
                target_col = getattr(target_alias.c, hop.target_field)
            except AttributeError as exc:
                raise ValueError(
                    "Unknown join field in related path hop: "
                    f"{hop.source_field!r} -> {hop.target_field!r}."
                ) from exc

            join_predicate = source_col == target_col
            if idx == 0:
                correlation_clause = join_predicate
            else:
                join_clauses.append(join_predicate)

            target_aliases.append(target_alias)
            current_alias = target_alias

        from_clause = target_aliases[0]
        for idx in range(1, len(target_aliases)):
            from_clause = from_clause.join(target_aliases[idx], join_clauses[idx - 1])

        return from_clause, correlation_clause, current_alias

    def _related_exists_clause(
        self,
        *,
        from_clause: Any,
        correlation_clause: Any,
        terminal_predicate: Any,
    ) -> Any:
        subquery = (
            sa_select(1)
            .select_from(from_clause)
            .where(and_(correlation_clause, terminal_predicate))
        )
        return subquery.exists()

    def _related_order_clause(self, table: Table, order_by: RelatedOrderBy) -> Any:
        from_clause, correlation_clause, terminal_alias = self._resolve_related_path(
            table=table,
            path_hops=order_by.path_hops,
            alias_prefix="rob",
        )

        try:
            terminal_col = getattr(terminal_alias.c, order_by.field)
        except AttributeError as exc:
            raise ValueError(
                f"Unknown field {order_by.field!r} in related order-by."
            ) from exc

        subquery = (
            sa_select(terminal_col)
            .select_from(from_clause)
            .where(correlation_clause)
            .limit(1)
            .scalar_subquery()
        )

        clause = subquery.desc() if order_by.descending else subquery.asc()
        if order_by.nulls_last:
            clause = clause.nulls_last()
        return clause

    def _predicates_for_group(self, table: Table, group: FilterGroup) -> Any | None:
        """Build a SQLAlchemy boolean expression for a single FilterGroup.

        All predicates in the group are combined with AND. If the group
        contains no predicates, returns None.
        """
        predicates = self._build_predicates(
            table=table,
            where=group.where,
            text_filters=group.text_filters,
            scalar_filters=group.scalar_filters,
            related_text_filters=getattr(group, "related_text_filters", []),
            related_scalar_filters=getattr(group, "related_scalar_filters", []),
        )

        if not predicates:
            return None

        return and_(*predicates)

    # pylint: disable=too-many-arguments
    # ylint: disable=too-many-positional-arguments
    def _apply_where(
        self,
        table: Table,
        stmt,
        where: Mapping[str, Any] | None,
        text_filters: Sequence[TextFilter] | None = None,
        scalar_filters: Sequence[ScalarFilter] | None = None,
    ) -> Any:
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
