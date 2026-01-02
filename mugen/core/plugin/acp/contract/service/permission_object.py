"""Provides a service contract for PermissionObject-related services."""

__all__ = ["IPermissionObjectService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import PermissionObjectDE


class IPermissionObjectService(
    ICrudService[PermissionObjectDE],
    ABC,
):
    """A service contract for PermissionObject-related services."""
