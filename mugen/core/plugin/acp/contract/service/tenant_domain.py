"""Provides a service contract for TenantDomain-related services."""

__all__ = ["ITenantDomainService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import TenantDomainDE


class ITenantDomainService(
    ICrudService[TenantDomainDE],
    ABC,
):
    """A service contract for TenantDomain-related services."""
