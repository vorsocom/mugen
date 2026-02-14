"""Unit tests for RDBMS gateway/service base contracts."""

from contextlib import asynccontextmanager
import unittest
from unittest.mock import AsyncMock, Mock

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService


class _GatewayUnderTest(IRelationalStorageGateway):
    def __init__(self, uow):
        self._uow = uow

    @asynccontextmanager
    async def unit_of_work(self):
        yield self._uow


class _Entity:
    pass


class _FakeRsg:
    def __init__(self):
        self.count_many = AsyncMock(return_value=3)
        self.insert_one = AsyncMock(return_value={"id": "n1", "name": "new"})
        self.get_one = AsyncMock(return_value={"id": "g1", "name": "got"})
        self.find_many = AsyncMock(
            return_value=[
                {"id": "l1", "name": "left"},
                {"id": "l2", "name": "right"},
            ]
        )
        self.find_many_partitioned_by_fk = AsyncMock(
            return_value=[{"id": "p1", "owner_id": "o1"}]
        )
        self.update_one = AsyncMock(return_value={"id": "u1", "name": "updated"})
        self.delete_one = AsyncMock(return_value={"id": "d1", "name": "deleted"})


class TestMugenContractRdbmsGateway(unittest.IsolatedAsyncioTestCase):
    """Ensures gateway convenience wrappers call into a UoW correctly."""

    async def test_gateway_helper_methods_delegate_to_uow(self) -> None:
        uow = Mock()
        uow.count = AsyncMock(return_value=11)
        uow.insert = AsyncMock(return_value={"id": "1"})
        uow.get_one = AsyncMock(return_value={"id": "2"})
        uow.find = AsyncMock(return_value=[{"id": "3"}])
        uow.find_partitioned_by_fk = AsyncMock(return_value=[{"id": "4"}])
        uow.update_one = AsyncMock(return_value={"id": "5"})
        uow.delete_one = AsyncMock(return_value={"id": "6"})
        uow.delete_many = AsyncMock(return_value=None)
        gateway = _GatewayUnderTest(uow)

        count = await gateway.count_many("t_count", filter_groups=[["x"]])
        inserted = await gateway.insert_one("t_insert", {"id": "1"})
        one = await gateway.get_one("t_get", {"id": "2"}, columns=["id"])
        found = await gateway.find_many(
            "t_find",
            columns=["id"],
            filter_groups=[["f"]],
            order_by=[("id", "asc")],
            limit=5,
            offset=2,
        )
        partitioned = await gateway.find_many_partitioned_by_fk(
            "t_part",
            fk_field="owner_id",
            fk_values=["a", "b"],
            columns=["id"],
            filter_groups=[["f"]],
            order_by=[("id", "asc")],
            per_fk_limit=10,
            per_fk_offset=1,
        )
        updated = await gateway.update_one("t_update", {"id": "5"}, {"x": 1})
        deleted = await gateway.delete_one("t_delete", {"id": "6"})
        await gateway.delete_many("t_delete_many", {"owner": "u"})

        self.assertEqual(count, 11)
        self.assertEqual(inserted, {"id": "1"})
        self.assertEqual(one, {"id": "2"})
        self.assertEqual(found, [{"id": "3"}])
        self.assertEqual(partitioned, [{"id": "4"}])
        self.assertEqual(updated, {"id": "5"})
        self.assertEqual(deleted, {"id": "6"})
        uow.count.assert_awaited_once_with("t_count", filter_groups=[["x"]])
        uow.insert.assert_awaited_once_with("t_insert", {"id": "1"})
        uow.get_one.assert_awaited_once_with("t_get", {"id": "2"}, columns=["id"])
        uow.find.assert_awaited_once_with(
            "t_find",
            columns=["id"],
            filter_groups=[["f"]],
            order_by=[("id", "asc")],
            limit=5,
            offset=2,
        )
        uow.find_partitioned_by_fk.assert_awaited_once_with(
            "t_part",
            fk_field="owner_id",
            fk_values=["a", "b"],
            columns=["id"],
            filter_groups=[["f"]],
            order_by=[("id", "asc")],
            per_fk_limit=10,
            per_fk_offset=1,
        )
        uow.update_one.assert_awaited_once_with(
            "t_update",
            {"id": "5"},
            {"x": 1},
            returning=True,
        )
        uow.delete_one.assert_awaited_once_with("t_delete", {"id": "6"})
        uow.delete_many.assert_awaited_once_with("t_delete_many", {"owner": "u"})


class TestMugenContractRdbmsServiceBase(unittest.IsolatedAsyncioTestCase):
    """Covers CRUD helpers and row-version flows for IRelationalService."""

    def _new_service(self):
        rsg = _FakeRsg()
        svc = IRelationalService(_Entity, "widgets", rsg)
        return svc, rsg

    async def test_crud_and_id_helpers(self) -> None:
        svc, rsg = self._new_service()

        self.assertEqual(svc.table, "widgets")
        self.assertEqual(svc.where_for_id("abc"), {"id": "abc"})
        self.assertEqual(await svc.count(filter_groups=[["f"]]), 3)

        created = await svc.create({"name": "new"})
        self.assertEqual(created.id, "n1")
        self.assertEqual(created.name, "new")

        got = await svc.get({"id": "g1"}, columns=["id", "name"])
        self.assertEqual(got.id, "g1")
        self.assertEqual(got.name, "got")
        rsg.get_one.return_value = None
        self.assertIsNone(await svc.get({"id": "none"}))

        listed = await svc.list(
            columns=["id"],
            filter_groups=[["f"]],
            order_by=[("id", "asc")],
            limit=2,
            offset=1,
        )
        self.assertEqual([x.id for x in listed], ["l1", "l2"])

        partitioned = await svc.list_partitioned_by_fk(
            fk_field="owner_id",
            fk_values=["o1"],
            columns=["id", "owner_id"],
            filter_groups=[["f"]],
            order_by=[("id", "asc")],
            per_fk_limit=1,
            per_fk_offset=0,
        )
        self.assertEqual(partitioned[0].owner_id, "o1")

        updated = await svc.update({"id": "u1"}, {"name": "updated"})
        self.assertEqual(updated.id, "u1")
        rsg.update_one.return_value = None
        self.assertIsNone(await svc.update({"id": "none"}, {"name": "x"}))

        deleted = await svc.delete({"id": "d1"})
        self.assertEqual(deleted.id, "d1")
        rsg.delete_one.return_value = None
        self.assertIsNone(await svc.delete({"id": "none"}))

        rsg.get_one.return_value = {"id": "byid"}
        by_id = await svc.get_by_id("byid")
        self.assertEqual(by_id.id, "byid")

        rsg.update_one.return_value = {"id": "byid", "name": "changed"}
        updated_by_id = await svc.update_by_id("byid", {"name": "changed"})
        self.assertEqual(updated_by_id.name, "changed")

        rsg.delete_one.return_value = {"id": "byid", "name": "gone"}
        deleted_by_id = await svc.delete_by_id("byid")
        self.assertEqual(deleted_by_id.name, "gone")

    async def test_row_version_helpers(self) -> None:
        svc, rsg = self._new_service()

        merged = svc._with_row_version({"id": "a"}, 7)
        self.assertEqual(merged, {"id": "a", "row_version": 7})

        with self.assertRaises(TypeError):
            svc._with_row_version({"id": "a"}, "7")

        row_version_updated = await svc.update_with_row_version(
            {"id": "u"},
            expected_row_version=3,
            changes={"name": "rv"},
        )
        self.assertEqual(row_version_updated.id, "u1")
        update_call = rsg.update_one.await_args.kwargs
        self.assertEqual(update_call["where"]["row_version"], 3)

        by_id_updated = await svc.update_by_id_with_row_version(
            "entity-1",
            expected_row_version=9,
            changes={"name": "rv2"},
        )
        self.assertEqual(by_id_updated.id, "u1")
        update_by_id_call = rsg.update_one.await_args.kwargs
        self.assertEqual(
            update_by_id_call["where"], {"id": "entity-1", "row_version": 9}
        )

        rsg.delete_one.return_value = {"id": "d-rv"}
        deleted = await svc.delete_with_row_version(
            {"id": "entity-1"},
            expected_row_version=5,
        )
        self.assertEqual(deleted.id, "d-rv")
        delete_call = rsg.delete_one.await_args.kwargs
        self.assertEqual(delete_call["where"], {"id": "entity-1", "row_version": 5})

        rsg.delete_one.return_value = None
        self.assertIsNone(
            await svc.delete_by_id_with_row_version(
                "entity-2",
                expected_row_version=8,
            )
        )
