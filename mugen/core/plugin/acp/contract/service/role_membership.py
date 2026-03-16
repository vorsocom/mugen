"""Provides a service contract for RoleMembership-related services."""

__all__ = ["IRoleMembershipService"]

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import RoleMembershipDE


class IRoleMembershipService(
    ICrudService[RoleMembershipDE],
    ABC,
):
    """A service contract for RoleMembership-related services."""

    @abstractmethod
    async def associate_roles_with_user(self, user: str, roles: list[str]) -> None:
        """Associate Roles with User."""

    @abstractmethod
    async def clear_user_roles(self, where: Mapping[str, Any]) -> None:
        """Remove all user <--> role associations matching `where`."""

    @abstractmethod
    async def get_role_memberships_by_user(
        self,
        where: Mapping[str, Any],
    ) -> Sequence[RoleMembershipDE]:
        """Retrieve all role membership records for a user from the DB."""
