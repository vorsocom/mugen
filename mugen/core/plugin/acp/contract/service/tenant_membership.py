"""Provides a service contract for TenantMembership-related services."""

__all__ = ["ITenantMembershipService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import TenantMembershipDE


class ITenantMembershipService(
    ICrudService[TenantMembershipDE],
    ABC,
):
    """A service contract for TenantMembership-related services."""
