"""Provides a domain entity for the TenantMembership DB model."""

__all__ = ["TenantMembershipDE"]

from dataclasses import dataclass
from datetime import datetime

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin
from mugen.core.plugin.acp.domain.mixin.user_scoped import UserScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class TenantMembershipDE(BaseDE, TenantScopedDEMixin, UserScopedDEMixin):
    """A domain entity for the TenantMembership DB model."""

    role_in_tenant: str | None = None

    status: str | None = None

    joined_at: datetime | None = None
