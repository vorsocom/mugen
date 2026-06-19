"""Provides a service for the GlobalRoleMembership declarative model."""

__all__ = ["GlobalRoleMembershipService"]

import uuid
from typing import Any, Mapping, Sequence

from quart import abort

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.plugin.acp.contract.service import IGlobalRoleMembershipService
from mugen.core.plugin.acp.domain import GlobalRoleMembershipDE

_GLOBAL_ROLE_TABLE = "admin_global_role"
_USER_TABLE = "admin_user"


class GlobalRoleMembershipService(
    IRelationalService[GlobalRoleMembershipDE],
    IGlobalRoleMembershipService,
):
    """A service for the GlobalRoleMembership declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=GlobalRoleMembershipDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def create(self, values: Mapping[str, Any]) -> GlobalRoleMembershipDE:
        user_id = values.get("user_id")
        global_role_id = values.get("global_role_id")
        if user_id is None or global_role_id is None:
            abort(400, "UserId and GlobalRoleId are required.")

        existing = await self.get(
            {
                "user_id": user_id,
                "global_role_id": global_role_id,
            }
        )
        if existing is not None:
            abort(409, "Global role membership already exists.")

        user = await self._rsg.get_one(
            _USER_TABLE,
            {
                "id": user_id,
                "deleted_at": None,
            },
        )
        if user is None:
            abort(400, "User does not exist or is deleted.")

        global_role = await self._rsg.get_one(
            _GLOBAL_ROLE_TABLE,
            {"id": global_role_id},
        )
        if global_role is None:
            abort(400, "Global role does not exist.")

        return await super().create(values)

    async def associate_roles_with_user(
        self,
        user: uuid.UUID,
        roles: list[uuid.UUID],
    ) -> None:
        for role in roles:
            association = await self.get(
                {
                    "user_id": user,
                    "global_role_id": role,
                },
            )
            if association is None:
                await self.create(
                    {
                        "user_id": user,
                        "global_role_id": role,
                    },
                )

    async def clear_user_roles(self, where: Mapping[str, Any]) -> None:
        await self._rsg.delete_many(self.table, where)

    async def get_role_memberships_by_user(
        self,
        where: Mapping[str, Any],
    ) -> Sequence[GlobalRoleMembershipDE]:
        return await self.list(filter_groups=[FilterGroup(where=where)])
