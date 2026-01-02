"""Provides a service contract for Role-related services."""

__all__ = ["IRoleService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import RoleDE


class IRoleService(
    ICrudService[RoleDE],
    ABC,
):
    """A service contract for Role-related services."""
