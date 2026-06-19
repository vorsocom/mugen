"""Unit tests for ACP membership services."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock, patch

from mugen.core.plugin.acp.service.global_role_membership import (
    GlobalRoleMembershipService,
)
from mugen.core.plugin.acp.service.role_membership import RoleMembershipService


class _Rsg:
    def __init__(self):
        self.delete_many = AsyncMock(return_value=None)
        self.get_one = AsyncMock(return_value=None)
        self.insert_one = AsyncMock(return_value=None)


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


class TestMugenAcpServiceMemberships(unittest.IsolatedAsyncioTestCase):
    """Covers association, clear, and list filters for role memberships."""

    async def test_global_role_membership_service_paths(self) -> None:
        rsg = _Rsg()
        svc = GlobalRoleMembershipService(table="global_role_memberships", rsg=rsg)
        user = uuid.uuid4()
        role_a = uuid.uuid4()
        role_b = uuid.uuid4()

        svc.get = AsyncMock(side_effect=[None, object()])
        svc.create = AsyncMock(return_value=None)
        await svc.associate_roles_with_user(user, [role_a, role_b])
        svc.create.assert_awaited_once_with(
            {
                "user_id": user,
                "global_role_id": role_a,
            }
        )

        await svc.clear_user_roles({"user_id": user})
        rsg.delete_many.assert_awaited_once_with(
            "global_role_memberships",
            {"user_id": user},
        )

        svc.list = AsyncMock(return_value=["x"])
        rows = await svc.get_role_memberships_by_user({"user_id": user})
        self.assertEqual(rows, ["x"])
        self.assertEqual(
            svc.list.await_args.kwargs["filter_groups"][0].where,
            {"user_id": user},
        )

    async def test_global_role_membership_create_validates_inputs(self) -> None:
        rsg = _Rsg()
        svc = GlobalRoleMembershipService(
            table="admin_global_role_membership",
            rsg=rsg,
        )
        user_id = uuid.uuid4()
        role_id = uuid.uuid4()
        membership_id = uuid.uuid4()

        svc.get = AsyncMock(return_value=None)
        rsg.get_one.side_effect = [
            {"id": user_id},
            {"id": role_id},
        ]
        rsg.insert_one.return_value = {
            "id": membership_id,
            "user_id": user_id,
            "global_role_id": role_id,
        }

        created = await svc.create(
            {
                "user_id": user_id,
                "global_role_id": role_id,
            }
        )

        self.assertEqual(created.id, membership_id)
        self.assertEqual(created.user_id, user_id)
        self.assertEqual(created.global_role_id, role_id)
        svc.get.assert_awaited_once_with(
            {
                "user_id": user_id,
                "global_role_id": role_id,
            }
        )
        self.assertEqual(rsg.get_one.await_args_list[0].args[0], "admin_user")
        self.assertEqual(
            rsg.get_one.await_args_list[0].args[1],
            {
                "id": user_id,
                "deleted_at": None,
            },
        )
        self.assertEqual(
            rsg.get_one.await_args_list[1].args,
            (
                "admin_global_role",
                {"id": role_id},
            ),
        )
        rsg.insert_one.assert_awaited_once_with(
            "admin_global_role_membership",
            {
                "user_id": user_id,
                "global_role_id": role_id,
            },
        )

    async def test_global_role_membership_create_rejects_duplicate(self) -> None:
        rsg = _Rsg()
        svc = GlobalRoleMembershipService(
            table="admin_global_role_membership",
            rsg=rsg,
        )
        svc.get = AsyncMock(return_value=object())

        with patch(
            "mugen.core.plugin.acp.service.global_role_membership.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.create(
                    {
                        "user_id": uuid.uuid4(),
                        "global_role_id": uuid.uuid4(),
                    }
                )

        self.assertEqual(ex.exception.code, 409)
        rsg.get_one.assert_not_awaited()
        rsg.insert_one.assert_not_awaited()

    async def test_global_role_membership_create_rejects_missing_ids(self) -> None:
        rsg = _Rsg()
        svc = GlobalRoleMembershipService(
            table="admin_global_role_membership",
            rsg=rsg,
        )

        with patch(
            "mugen.core.plugin.acp.service.global_role_membership.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.create({})

        self.assertEqual(ex.exception.code, 400)
        rsg.get_one.assert_not_awaited()
        rsg.insert_one.assert_not_awaited()

    async def test_global_role_membership_create_rejects_missing_user(self) -> None:
        rsg = _Rsg()
        svc = GlobalRoleMembershipService(
            table="admin_global_role_membership",
            rsg=rsg,
        )
        svc.get = AsyncMock(return_value=None)
        rsg.get_one.return_value = None

        with patch(
            "mugen.core.plugin.acp.service.global_role_membership.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.create(
                    {
                        "user_id": uuid.uuid4(),
                        "global_role_id": uuid.uuid4(),
                    }
                )

        self.assertEqual(ex.exception.code, 400)
        rsg.insert_one.assert_not_awaited()

    async def test_global_role_membership_create_rejects_missing_role(self) -> None:
        rsg = _Rsg()
        svc = GlobalRoleMembershipService(
            table="admin_global_role_membership",
            rsg=rsg,
        )
        svc.get = AsyncMock(return_value=None)
        rsg.get_one.side_effect = [{"id": uuid.uuid4()}, None]

        with patch(
            "mugen.core.plugin.acp.service.global_role_membership.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.create(
                    {
                        "user_id": uuid.uuid4(),
                        "global_role_id": uuid.uuid4(),
                    }
                )

        self.assertEqual(ex.exception.code, 400)
        rsg.insert_one.assert_not_awaited()

    async def test_role_membership_service_paths(self) -> None:
        rsg = _Rsg()
        svc = RoleMembershipService(table="role_memberships", rsg=rsg)
        user = uuid.uuid4()
        role_a = uuid.uuid4()
        role_b = uuid.uuid4()

        svc.get = AsyncMock(side_effect=[None, object()])
        svc.create = AsyncMock(return_value=None)
        await svc.associate_roles_with_user(user, [role_a, role_b])
        svc.create.assert_awaited_once_with(
            {
                "user_id": user,
                "role_id": role_a,
            }
        )

        await svc.clear_user_roles({"user_id": user})
        rsg.delete_many.assert_awaited_once_with(
            "role_memberships",
            {"user_id": user},
        )

        svc.list = AsyncMock(return_value=["x"])
        rows = await svc.get_role_memberships_by_user({"user_id": user})
        self.assertEqual(rows, ["x"])
        self.assertEqual(
            svc.list.await_args.kwargs["filter_groups"][0].where,
            {"user_id": user},
        )
