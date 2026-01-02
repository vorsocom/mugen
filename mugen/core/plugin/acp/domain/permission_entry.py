"""Provides a domain entity for the PermissionEntry DB model."""

__all__ = ["PermissionEntryDE"]

import uuid
from dataclasses import dataclass
from typing import Type

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.role_scoped import RoleScopedDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class PermissionEntryDE(BaseDE, RoleScopedDEMixin, TenantScopedDEMixin):
    """A domain entity for the PermissionEntry DB model."""

    permitted: bool | None = None

    permission_object_id: uuid.UUID | None = None

    permission_type_id: uuid.UUID | None = None

    permission_object: Type["PermissionObjectDE"] | None = None  # type: ignore

    permission_type: Type["PermissionTypeDE"] | None = None  # type: ignore
