"""Provides an ORM for many-to-many relationships between users and global roles."""

__all__ = ["GlobalRoleMembership"]

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, relationship

from mugen.core.plugin.acp.model.mixin.global_role_scoped import GlobalRoleScopedMixin
from mugen.core.plugin.acp.model.mixin.user_scoped import UserScopedMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class GlobalRoleMembership(
    ModelBase,
    GlobalRoleScopedMixin,
    UserScopedMixin,
):
    """An ORM for many-to-many relationships between users and global roles."""

    __tablename__ = "admin_global_role_membership"

    global_role: Mapped["GlobalRole"] = relationship(  # type: ignore
        back_populates="global_role_memberships",
    )

    user: Mapped["User"] = relationship(  # type: ignore
        back_populates="global_role_memberships",
    )

    __table_args__ = (
        UniqueConstraint(
            "global_role_id",
            "user_id",
            name="ux_global_role_membership__role_user",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"GlobalRoleMembership(id={self.id!r})"
