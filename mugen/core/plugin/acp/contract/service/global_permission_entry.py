"""Provides a service contract for GlobalPermissionEntry-related services."""

__all__ = ["IGlobalPermissionEntryService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import GlobalPermissionEntryDE


class IGlobalPermissionEntryService(
    ICrudService[GlobalPermissionEntryDE],
    ABC,
):
    """A service contract for GlobalPermissionEntry-related services."""
