"""Provides an ORM for many-to-many relationships between users and tenants."""

__all__ = ["TenantMembership"]

import enum
from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.plugin.acp.model.mixin.user_scoped import UserScopedMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class TenantMembershipRole(str, enum.Enum):
    """Tenant membership role enum types."""

    ADMIN = "admin"

    MEMBER = "member"

    OWNER = "owner"


class TenantMembershipStatus(str, enum.Enum):
    """Tenant membership status enum types."""

    ACTIVE = "active"

    INVITED = "invited"

    SUSPENDED = "suspended"


# pylint: disable=too-few-public-methods
class TenantMembership(ModelBase, TenantScopedMixin, UserScopedMixin):
    """An ORM for many-to-many relationships between User and Tenant."""

    __tablename__ = "admin_tenant_membership"

    role_in_tenant: Mapped[str] = mapped_column(
        PGENUM(
            TenantMembershipRole,
            name="admin_tenant_membership_role",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'member'"),
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            TenantMembershipStatus,
            name="admin_tenant_membership_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'active'"),
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    tenant: Mapped["Tenant"] = relationship(  # type: ignore
        back_populates="tenant_memberships",
    )

    user: Mapped["User"] = relationship(  # type: ignore
        back_populates="tenant_memberships",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_tenant_membership__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            name="ux_tenant_membership__tenant_user",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"TenantMembership(id={self.id!r})"
