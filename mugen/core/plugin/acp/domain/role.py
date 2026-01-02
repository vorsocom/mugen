"""Provides a domain entity for the Role DB model."""

__all__ = ["RoleDE"]

from dataclasses import dataclass
from typing import Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class RoleDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the Role DB model."""

    namespace: str | None = None

    name: str | None = None

    display_name: str | None = None

    permission_entries: Sequence["PermissionEntryDE"] | None = None  # type: ignore

    role_memberships: Sequence["RoleMembershipDE"] | None = None  # type: ignore
