"""Provides an ORM for permission types."""

__all__ = ["PermissionType"]

from typing import List

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class PermissionType(ModelBase):
    """An ORM for permission types."""

    __tablename__ = "admin_permission_type"

    namespace: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=False,
    )

    global_permission_entries: Mapped[List["GlobalPermissionEntry"]] = (
        relationship(  # type: ignore
            back_populates="permission_object",
        )
    )

    permission_entries: Mapped[List["PermissionEntry"]] = relationship(  # type: ignore
        back_populates="permission_type",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(namespace)) > 0",
            name="ck_permission_type__namespace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_permission_type__name_nonempty",
        ),
        UniqueConstraint(
            "namespace",
            "name",
            name="ux_permission_type__namespace_name",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"PermissionType(id={self.id!r})"
