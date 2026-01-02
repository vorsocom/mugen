"""Provides a service contract for PermissionType-related services."""

__all__ = ["IPermissionTypeService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import PermissionTypeDE


class IPermissionTypeService(
    ICrudService[PermissionTypeDE],
    ABC,
):
    """A service contract for PermissionType-related services."""
