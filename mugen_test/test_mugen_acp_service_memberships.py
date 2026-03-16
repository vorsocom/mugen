"""Unit tests for ACP membership services."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock

from mugen.core.plugin.acp.service.global_role_membership import (
    GlobalRoleMembershipService,
)
from mugen.core.plugin.acp.service.role_membership import RoleMembershipService


class _Rsg:
    def __init__(self):
        self.delete_many = AsyncMock(return_value=None)


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
        rsg.delete_many.assert_awaited_once_with("global_role_memberships", {"user_id": user})

        svc.list = AsyncMock(return_value=["x"])
        rows = await svc.get_role_memberships_by_user({"user_id": user})
        self.assertEqual(rows, ["x"])
        self.assertEqual(svc.list.await_args.kwargs["filter_groups"][0].where, {"user_id": user})

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
        rsg.delete_many.assert_awaited_once_with("role_memberships", {"user_id": user})

        svc.list = AsyncMock(return_value=["x"])
        rows = await svc.get_role_memberships_by_user({"user_id": user})
        self.assertEqual(rows, ["x"])
        self.assertEqual(svc.list.await_args.kwargs["filter_groups"][0].where, {"user_id": user})
