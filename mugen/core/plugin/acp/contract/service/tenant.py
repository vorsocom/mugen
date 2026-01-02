"""Provides a service contract for Tenant-related services."""

__all__ = ["ITenantService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import TenantDE


class ITenantService(
    ICrudService[TenantDE],
    ABC,
):
    """A service contract for Tenant-related services."""
