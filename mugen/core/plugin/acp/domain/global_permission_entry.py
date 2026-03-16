"""Provides a domain entity for the GlobalPermissionEntry DB model."""

__all__ = ["GlobalPermissionEntryDE"]

import uuid
from dataclasses import dataclass
from typing import Type

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.global_role_scoped import (
    GlobalRoleScopedDEMixin,
)


# pylint: disable=too-many-instance-attributes
@dataclass
class GlobalPermissionEntryDE(BaseDE, GlobalRoleScopedDEMixin):
    """A domain entity for the GlobalPermissionEntry DB model."""

    permitted: bool | None = None

    permission_object_id: uuid.UUID | None = None

    permission_type_id: uuid.UUID | None = None

    permission_object: Type["PermissionObjectDE"] | None = None  # type: ignore

    permission_type: Type["PermissionTypeDE"] | None = None  # type: ignore
