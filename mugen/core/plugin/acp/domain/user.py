"""Provides a domain entity for the User DB model."""

__all__ = ["UserDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.person_scoped import PersonScopedDEMixin
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class UserDE(BaseDE, PersonScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the User DB model."""

    locked_at: datetime | None = None

    locked_by_user_id: uuid.UUID | None = None

    password_hash: str | None = None

    password_changed_at: datetime | None = None

    password_changed_by_user_id: uuid.UUID | None = None

    username: str | None = None

    login_email: str | None = None

    last_login_at: datetime | None = None

    failed_login_count: int | None = None

    token_version: int | None = None

    global_role_memberships: Sequence["GlobalRoleMembershipDE"] | None = None  # type: ignore

    refresh_tokens: Sequence["RefreshTokenDE"] | None = None  # type: ignore

    role_memberships: Sequence["RoleMembershipDE"] | None = None  # type: ignore

    tenant_memberships: Sequence["TenantMembershipDE"] | None = None  # type: ignore
