"""Provides an ORM for tenants."""

__all__ = ["Tenant"]

import enum

from sqlalchemy import CheckConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import ENUM as PGENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class TenantStatus(str, enum.Enum):
    """Tenant status enum types."""

    ACTIVE = "active"

    SUSPENDED = "suspended"


# pylint: disable=too-few-public-methods
class Tenant(ModelBase, SoftDeleteMixin):
    """An ORM for tenants."""

    __tablename__ = "admin_tenant"

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            TenantStatus,
            name="admin_tenant_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'active'"),
    )

    permission_entries: Mapped[list["PermissionEntries"]] = (
        relationship(  # type: ignore
            back_populates="tenant",
            cascade="save-update, merge",
        )
    )

    roles: Mapped[list["Roles"]] = relationship(  # type: ignore
        back_populates="tenant",
        cascade="save-update, merge",
    )

    role_memberships: Mapped[list["RoleMembership"]] = relationship(  # type: ignore
        back_populates="tenant",
        cascade="save-update, merge",
    )

    tenant_domains: Mapped[list["TenantDomain"]] = relationship(  # type: ignore
        back_populates="tenant",
        cascade="save-update, merge",
    )

    tenant_invitations: Mapped[list["TenantInvitation"]] = relationship(  # type: ignore
        back_populates="tenant",
        cascade="save-update, merge",
    )

    tenant_memberships: Mapped[list["TenantMembership"]] = relationship(  # type: ignore
        back_populates="tenant",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_tenant__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(slug)) > 0",
            name="ck_tenant__slug_nonempty",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_tenant__not_deleted_and_not_deleted_by",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"Tenant(id={self.id!r})"
