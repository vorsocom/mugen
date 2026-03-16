"""Provides a domain entity for the GlobalRoleMembership DB model."""

__all__ = ["GlobalRoleMembershipDE"]

from dataclasses import dataclass

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.global_role_scoped import (
    GlobalRoleScopedDEMixin,
)
from mugen.core.plugin.acp.domain.mixin.user_scoped import UserScopedDEMixin


@dataclass
class GlobalRoleMembershipDE(BaseDE, GlobalRoleScopedDEMixin, UserScopedDEMixin):
    """A domain entity for the GlobalRoleMembership DB model."""
