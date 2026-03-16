"""Provides an ORM for many-to-many relationships between users and roles."""

__all__ = ["RoleMembership"]

from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, relationship

from mugen.core.plugin.acp.model.mixin.role_scoped import RoleScopedMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.plugin.acp.model.mixin.user_scoped import UserScopedMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class RoleMembership(
    ModelBase,
    RoleScopedMixin,
    TenantScopedMixin,
    UserScopedMixin,
):
    """An ORM for many-to-many relationships between users and roles."""

    __tablename__ = "admin_role_membership"

    role: Mapped["Role"] = relationship(  # type: ignore
        back_populates="role_memberships",
    )

    tenant: Mapped["Tenant"] = relationship(  # type: ignore
        back_populates="role_memberships",
    )

    user: Mapped["User"] = relationship(  # type: ignore
        back_populates="role_memberships",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            (
                "tenant_id",
                "role_id",
            ),
            (
                f"{CORE_SCHEMA_TOKEN}.admin_role.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.admin_role.id",
            ),
            name="fkx_role_membership__tenant_role",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            (
                "tenant_id",
                "user_id",
            ),
            (
                f"{CORE_SCHEMA_TOKEN}.admin_tenant_membership.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.admin_tenant_membership.user_id",
            ),
            name="fkx_role_membership__tenant_user_membership",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_role_membership__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "role_id",
            "user_id",
            name="ux_role_membership__tenant_role_user",
        ),
        Index(
            "ix_role_membership__tenant_user",
            "tenant_id",
            "user_id",
        ),
        Index(
            "ix_role_membership__tenant_role",
            "tenant_id",
            "role_id",
        ),
        Index(
            "ix_role_membership__tenant_role_user",
            "tenant_id",
            "role_id",
            "user_id",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"RoleMembership(id={self.id!r})"
