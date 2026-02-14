"""Unit tests for mugen.core.gateway.storage.rdbms.sqla.sqla_uow."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import Column, Integer, MetaData, String, Table, select as sa_select

from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    RowVersionConflict,
    ScalarFilter,
    ScalarFilterOp,
    TextFilter,
    TextFilterOp,
)
from mugen.core.gateway.storage.rdbms.sqla.sqla_uow import (
    SQLAlchemyRelationalUnitOfWork,
)


class _FakeMappings:
    def __init__(self, rows):
        self._rows = list(rows)

    def one(self):
        if len(self._rows) != 1:
            raise LookupError("Expected exactly one row.")
        return self._rows[0]

    def one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) == 1:
            return self._rows[0]
        raise LookupError("Expected zero or one row.")

    def __iter__(self):
        return iter(self._rows)


class _FakeResult:
    def __init__(
        self,
        *,
        rows=None,
        scalar_value=None,
        scalar_one_or_none_value=None,
        rowcount: int = 0,
    ):
        self._rows = list(rows or [])
        self._scalar_value = scalar_value
        self._scalar_one_or_none_value = scalar_one_or_none_value
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar_value

    def mappings(self):
        return _FakeMappings(self._rows)

    def scalar_one_or_none(self):
        return self._scalar_one_or_none_value


class _UnhashableValue:
    __hash__ = None

    def __init__(self, value):
        self.value = value


class TestMugenSQLAUow(unittest.IsolatedAsyncioTestCase):
    """Covers SQLAlchemyRelationalUnitOfWork control-flow and predicate branches."""

    def setUp(self) -> None:
        metadata = MetaData()
        self.table = Table(
            "widgets",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("tenant_id", Integer),
            Column("name", String(64)),
            Column("score", Integer),
            Column("row_version", Integer),
        )
        self.session = AsyncMock()
        self.uow = SQLAlchemyRelationalUnitOfWork(
            session=self.session,
            tables={"widgets": self.table},
        )

    async def test_count_insert_get_one_and_find_paths(self) -> None:
        self.session.execute = AsyncMock(
            side_effect=[
                _FakeResult(scalar_value=1),
                _FakeResult(scalar_value=3),
                _FakeResult(scalar_value=None),
                _FakeResult(rows=[{"id": 1, "name": "Ada"}]),
                _FakeResult(),
                _FakeResult(rows=[{"id": 1, "name": "Ada"}]),
                _FakeResult(rows=[]),
                _FakeResult(rows=[{"id": 7, "name": "Kai"}]),
                _FakeResult(
                    rows=[
                        {"id": 1, "name": "Ada"},
                        {"id": 2, "name": "Bob"},
                    ]
                ),
                _FakeResult(rows=[{"id": 9, "name": "Zed"}]),
            ]
        )

        group_one = FilterGroup(where={"tenant_id": 10})
        group_two = FilterGroup(
            text_filters=[TextFilter(field="name", op=TextFilterOp.CONTAINS, value="a")]
        )

        single_group_count = await self.uow.count("widgets", filter_groups=[group_one])
        self.assertEqual(single_group_count, 1)

        count = await self.uow.count("widgets", filter_groups=[group_one, group_two])
        self.assertEqual(count, 3)

        zero_count = await self.uow.count("widgets", filter_groups=[FilterGroup()])
        self.assertEqual(zero_count, 0)

        created = await self.uow.insert(
            "widgets",
            {"id": 1, "tenant_id": 10, "name": "Ada"},
            returning=True,
        )
        self.assertEqual(created, {"id": 1, "name": "Ada"})

        not_returned = await self.uow.insert(
            "widgets",
            {"id": 2, "tenant_id": 10, "name": "Bob"},
            returning=False,
        )
        self.assertIsNone(not_returned)

        row = await self.uow.get_one(
            "widgets",
            {"id": 1},
            columns=["id", "name"],
        )
        self.assertEqual(row, {"id": 1, "name": "Ada"})

        no_row = await self.uow.get_one("widgets", {"id": 404})
        self.assertIsNone(no_row)

        found_single_group = await self.uow.find(
            "widgets",
            columns=["id", "name"],
            filter_groups=[group_one],
        )
        self.assertEqual(found_single_group, [{"id": 7, "name": "Kai"}])

        found = await self.uow.find(
            "widgets",
            columns=["id", "name"],
            filter_groups=[group_one, group_two],
            order_by=[OrderBy("name"), OrderBy("id", descending=True)],
            limit=10,
            offset=2,
        )
        self.assertEqual(found, [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bob"}])

        found_all_cols = await self.uow.find("widgets")
        self.assertEqual(found_all_cols, [{"id": 9, "name": "Zed"}])

        with self.assertRaises(ValueError):
            await self.uow.get_one("widgets", {"id": 1}, columns=["does_not_exist"])

        with self.assertRaises(ValueError):
            await self.uow.find("widgets", columns=["does_not_exist"])

    async def test_find_partitioned_by_fk_paths(self) -> None:
        self.assertEqual(
            await self.uow.find_partitioned_by_fk(
                "widgets",
                fk_field="tenant_id",
                fk_values=[],
            ),
            [],
        )
        self.assertEqual(
            await self.uow.find_partitioned_by_fk(
                "widgets",
                fk_field="tenant_id",
                fk_values=iter(()),
            ),
            [],
        )

        self.session.execute = AsyncMock(
            side_effect=[
                _FakeResult(rows=[{"id": 1, "tenant_id": 10, "name": "Ada"}]),
                _FakeResult(rows=[{"id": 4, "tenant_id": 11, "name": "Bea"}]),
                _FakeResult(rows=[{"id": 2, "tenant_id": 11, "name": "Bob"}]),
                _FakeResult(rows=[{"id": 3, "tenant_id": 12, "name": "Cam"}]),
            ]
        )

        by_fk = await self.uow.find_partitioned_by_fk(
            "widgets",
            fk_field="tenant_id",
            fk_values=[10, 10, 11],
            columns=["id", "name"],
            filter_groups=[
                FilterGroup(where={"score": 5}),
                FilterGroup(
                    text_filters=[
                        TextFilter(field="name", op=TextFilterOp.CONTAINS, value="a")
                    ]
                ),
            ],
            order_by=[OrderBy("name")],
            per_fk_limit=2,
            per_fk_offset=1,
            tie_breaker_field="id",
        )
        self.assertEqual(by_fk, [{"id": 1, "tenant_id": 10, "name": "Ada"}])

        by_fk_single_group = await self.uow.find_partitioned_by_fk(
            "widgets",
            fk_field="tenant_id",
            fk_values=[11],
            columns=["id", "name"],
            filter_groups=[FilterGroup(where={"score": 5})],
            per_fk_limit=1,
            per_fk_offset=0,
        )
        self.assertEqual(by_fk_single_group, [{"id": 4, "tenant_id": 11, "name": "Bea"}])

        by_fk_offset_only = await self.uow.find_partitioned_by_fk(
            "widgets",
            fk_field="tenant_id",
            fk_values=[10],
            order_by=[OrderBy("id", descending=True)],
            per_fk_limit=None,
            per_fk_offset=1,
            tie_breaker_field="id",
        )
        self.assertEqual(by_fk_offset_only, [{"id": 2, "tenant_id": 11, "name": "Bob"}])

        unhashable = _UnhashableValue(12)
        by_fk_unhashable = await self.uow.find_partitioned_by_fk(
            "widgets",
            fk_field="tenant_id",
            fk_values=[unhashable],
            order_by=None,
            per_fk_limit=1,
            per_fk_offset=0,
        )
        self.assertEqual(by_fk_unhashable, [{"id": 3, "tenant_id": 12, "name": "Cam"}])

        with self.assertRaises(ValueError):
            await self.uow.find_partitioned_by_fk(
                "widgets",
                fk_field="tenant_id",
                fk_values=[1],
                per_fk_offset=-1,
            )

        with self.assertRaises(ValueError):
            await self.uow.find_partitioned_by_fk(
                "widgets",
                fk_field="tenant_id",
                fk_values=[1],
                per_fk_limit=-1,
            )

        with self.assertRaises(ValueError):
            await self.uow.find_partitioned_by_fk(
                "widgets",
                fk_field="tenant_id",
                fk_values=[1],
                columns=["missing_column"],
            )

    async def test_update_delete_and_conflict_helpers(self) -> None:
        with patch.object(self.uow, "get_one", new=AsyncMock(return_value={"id": 1})) as get:
            row = await self.uow.update_one(
                "widgets",
                where={"id": 1},
                changes={},
                returning=True,
            )
            self.assertEqual(row, {"id": 1})
            get.assert_awaited_once()

        no_return_when_no_changes = await self.uow.update_one(
            "widgets",
            where={"id": 1},
            changes={},
            returning=False,
        )
        self.assertIsNone(no_return_when_no_changes)

        self.session.execute = AsyncMock(return_value=_FakeResult(rowcount=0))
        with patch.object(
            self.uow,
            "_raise_if_row_version_conflict",
            new=AsyncMock(),
        ) as raise_conflict:
            updated = await self.uow.update_one(
                "widgets",
                where={"id": 1, "row_version": 7},
                changes={"name": "Updated"},
                returning=False,
            )
            self.assertIsNone(updated)
            raise_conflict.assert_awaited_once()

        self.session.execute = AsyncMock(return_value=_FakeResult(rows=[{"id": 1, "name": "A"}]))
        updated_row = await self.uow.update_one(
            "widgets",
            where={"id": 1, "row_version": 1},
            changes={"name": "A"},
            returning=True,
        )
        self.assertEqual(updated_row, {"id": 1, "name": "A"})

        self.session.execute = AsyncMock(return_value=_FakeResult(rows=[]))
        with patch.object(
            self.uow,
            "_raise_if_row_version_conflict",
            new=AsyncMock(),
        ) as raise_conflict:
            updated_none = await self.uow.update_one(
                "widgets",
                where={"id": 2, "row_version": 1},
                changes={"name": "B"},
                returning=True,
            )
            self.assertIsNone(updated_none)
            raise_conflict.assert_awaited_once()

        self.session.execute = AsyncMock(return_value=_FakeResult(rows=[{"id": 1}]))
        deleted = await self.uow.delete_one("widgets", where={"id": 1})
        self.assertEqual(deleted, {"id": 1})

        self.session.execute = AsyncMock(return_value=_FakeResult(rows=[]))
        with patch.object(
            self.uow,
            "_raise_if_row_version_conflict",
            new=AsyncMock(),
        ) as raise_conflict:
            deleted_none = await self.uow.delete_one(
                "widgets",
                where={"id": 1, "row_version": 3},
            )
            self.assertIsNone(deleted_none)
            raise_conflict.assert_awaited_once()

        self.session.execute = AsyncMock(return_value=_FakeResult())
        await self.uow.delete_many("widgets", where={"tenant_id": 10})
        self.session.execute.assert_awaited_once()

        base_where = self.uow._where_without_row_version({"id": 5, "row_version": 9})  # pylint: disable=protected-access
        self.assertEqual(base_where, {"id": 5})

        with self.assertRaises(RowVersionConflict):
            await self.uow._raise_if_row_version_conflict(  # pylint: disable=protected-access
                "widgets",
                self.table,
                {"row_version": 4},
            )

        self.session.execute = AsyncMock(
            return_value=_FakeResult(scalar_one_or_none_value=None)
        )
        no_conflict = await self.uow._raise_if_row_version_conflict(  # pylint: disable=protected-access
            "widgets",
            self.table,
            {"id": 5, "row_version": 7},
        )
        self.assertIsNone(no_conflict)

        self.session.execute = AsyncMock(
            return_value=_FakeResult(scalar_one_or_none_value=8)
        )
        with self.assertRaises(RowVersionConflict):
            await self.uow._raise_if_row_version_conflict(  # pylint: disable=protected-access
                "widgets",
                self.table,
                {"id": 5, "row_version": 7},
            )

    def test_predicate_helper_branches_and_errors(self) -> None:
        text_filters = [
            TextFilter(field="name", op=TextFilterOp.CONTAINS, value="Ada"),
            TextFilter(
                field="name",
                op=TextFilterOp.STARTSWITH,
                value="A",
                case_sensitive=True,
            ),
            TextFilter(field="name", op=TextFilterOp.ENDSWITH, value="a"),
        ]
        scalar_filters = [
            ScalarFilter(field="score", op=ScalarFilterOp.LT, value=100),
            ScalarFilter(field="score", op=ScalarFilterOp.LTE, value=100),
            ScalarFilter(field="score", op=ScalarFilterOp.GT, value=1),
            ScalarFilter(field="score", op=ScalarFilterOp.GTE, value=1),
            ScalarFilter(field="score", op=ScalarFilterOp.NE, value=9),
            ScalarFilter(field="id", op=ScalarFilterOp.IN, value=[1, 2, 3]),
            ScalarFilter(field="id", op=ScalarFilterOp.IN, value=[]),
            ScalarFilter(field="score", op=ScalarFilterOp.BETWEEN, value=(1, 10)),
        ]

        clauses = self.uow._build_predicates(  # pylint: disable=protected-access
            self.table,
            where={"tenant_id": 1},
            text_filters=text_filters,
            scalar_filters=scalar_filters,
        )
        self.assertGreater(len(clauses), 1)

        group_expr = self.uow._predicates_for_group(  # pylint: disable=protected-access
            self.table,
            FilterGroup(where={"id": 1}),
        )
        self.assertIsNotNone(group_expr)

        empty_group_expr = self.uow._predicates_for_group(  # pylint: disable=protected-access
            self.table,
            FilterGroup(),
        )
        self.assertIsNone(empty_group_expr)

        base_stmt = sa_select(self.table)
        same_stmt = self.uow._apply_where(  # pylint: disable=protected-access
            self.table,
            base_stmt,
            where=None,
            text_filters=None,
            scalar_filters=None,
        )
        self.assertIs(same_stmt, base_stmt)

        filtered_stmt = self.uow._apply_where(  # pylint: disable=protected-access
            self.table,
            base_stmt,
            where={"id": 1},
        )
        self.assertIsNot(filtered_stmt, base_stmt)

        with self.assertRaises(TypeError):
            self.uow._build_predicates(  # pylint: disable=protected-access
                self.table,
                scalar_filters=[
                    ScalarFilter(field="id", op=ScalarFilterOp.IN, value="not-iterable")
                ],
            )

        with self.assertRaises(ValueError):
            self.uow._build_predicates(  # pylint: disable=protected-access
                self.table,
                text_filters=[TextFilter(field="name", op=object(), value="x")],
            )

        with self.assertRaises(ValueError):
            self.uow._build_predicates(  # pylint: disable=protected-access
                self.table,
                scalar_filters=[ScalarFilter(field="id", op=object(), value=1)],
            )

        with self.assertRaises(KeyError):
            self.uow._get_table("missing")  # pylint: disable=protected-access
