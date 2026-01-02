"""Provides a service contract for PermissionEntry-related services."""

__all__ = ["IPermissionEntryService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import PermissionEntryDE


class IPermissionEntryService(
    ICrudService[PermissionEntryDE],
    ABC,
):
    """A service contract for PermissionEntry-related services."""
