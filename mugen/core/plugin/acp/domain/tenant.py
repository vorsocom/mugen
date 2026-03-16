"""Provides a domain entity for the Tenant DB model."""

__all__ = ["TenantDE"]

from dataclasses import dataclass
from typing import Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class TenantDE(BaseDE, SoftDeleteDEMixin):
    """A domain entity for the Tenant DB model."""

    name: str | None = None

    slug: str | None = None

    status: str | None = None

    permission_entries: Sequence["PermissionEntryDE"] | None = None  # type: ignore

    roles: Sequence["RoleDE"] | None = None  # type: ignore

    role_memberships: Sequence["RoleMembershipDE"] | None = None  # type: ignore

    tenant_domains: Sequence["TenantDomainDE"] | None = None  # type: ignore

    tenant_invitations: Sequence["TenantInvitationDE"] | None = None  # type: ignore

    tenant_memberships: Sequence["TenantMembershipDE"] | None = None  # type: ignore
