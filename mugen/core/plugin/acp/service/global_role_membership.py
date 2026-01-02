"""Provides a service for the GlobalRoleMembership declarative model."""

__all__ = ["GlobalRoleMembershipService"]

import uuid
from typing import Any, Mapping, Sequence

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.plugin.acp.contract.service import IGlobalRoleMembershipService
from mugen.core.plugin.acp.domain import GlobalRoleMembershipDE


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
