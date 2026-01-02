"""Provides a service contract for TenantInvitation-related services."""

__all__ = ["ITenantInvitationService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import TenantInvitationDE


class ITenantInvitationService(
    ICrudService[TenantInvitationDE],
    ABC,
):
    """A service contract for TenantDomain-related services."""
