"""Provides a domain entity for the GlobalRole DB model."""

__all__ = ["GlobalRoleDE"]

from dataclasses import dataclass
from typing import Sequence

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class GlobalRoleDE(BaseDE):  # pylint: disable=too-many-instance-attributes
    """A domain entity for the GlobalRole DB model."""

    namespace: str | None = None

    name: str | None = None

    display_name: str | None = None

    global_permission_entries: Sequence["GlobalPermissionEntryDE"] | None = None  # type: ignore

    global_role_memberships: Sequence["GlobalRoleMembershipDE"] | None = None  # type: ignore
