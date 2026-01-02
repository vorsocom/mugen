"""Provides a service contract for GlobalRole-related services."""

__all__ = ["IGlobalRoleService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import GlobalRoleDE


class IGlobalRoleService(
    ICrudService[GlobalRoleDE],
    ABC,
):
    """A service contract for GlobalRole-related services."""
