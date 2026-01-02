"""Provides an ORM for global roles."""

__all__ = ["GlobalRole"]

from typing import List

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class GlobalRole(ModelBase):
    """An ORM for global roles."""

    __tablename__ = "admin_global_role"

    namespace: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=False,
    )

    display_name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    global_permission_entries: Mapped[List["GlobalPermissionEntry"]] = relationship(  # type: ignore
        back_populates="global_role",
    )

    global_role_memberships: Mapped[List["GlobalRoleMembership"]] = relationship(  # type: ignore
        back_populates="global_role",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(namespace)) > 0",
            name="ck_global_role__namespace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_global_role__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_global_role__display_name_nonempty",
        ),
        UniqueConstraint(
            "namespace",
            "name",
            name="ux_global_role__namespace_name",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"GlobalRole(id={self.id!r})"
