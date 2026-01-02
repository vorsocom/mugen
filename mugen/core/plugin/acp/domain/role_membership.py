"""Provides a domain entity for the RoleMembership DB model."""

__all__ = ["RoleMembershipDE"]

from dataclasses import dataclass

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.role_scoped import RoleScopedDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin
from mugen.core.plugin.acp.domain.mixin.user_scoped import UserScopedDEMixin


@dataclass
class RoleMembershipDE(
    BaseDE,
    RoleScopedDEMixin,
    TenantScopedDEMixin,
    UserScopedDEMixin,
):
    """A domain entity for the RoleMembership DB model."""
