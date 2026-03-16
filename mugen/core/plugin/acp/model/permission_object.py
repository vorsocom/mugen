"""Provides an ORM for permission objects."""

__all__ = ["PermissionObject"]

import enum
from typing import List

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import ENUM as PGENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class PermissionObjectStatus(str, enum.Enum):
    """Permission object status enum values."""

    ACTIVE = "active"

    DEPRECATED = "deprecated"


# pylint: disable=too-few-public-methods
class PermissionObject(ModelBase):
    """An ORM for permission objects."""

    __tablename__ = "admin_permission_object"

    namespace: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=False,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            PermissionObjectStatus,
            name="admin_permission_object_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'active'"),
    )

    global_permission_entries: Mapped[List["GlobalPermissionEntry"]] = (
        relationship(  # type: ignore
            back_populates="permission_object",
        )
    )

    permission_entries: Mapped[List["PermissionEntry"]] = relationship(  # type: ignore
        back_populates="permission_object",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(namespace)) > 0",
            name="ck_permission_object__namespace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_permission_object__name_nonempty",
        ),
        UniqueConstraint(
            "namespace",
            "name",
            name="ux_permission_object__namespace_name",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"PermissionObject(id={self.id!r})"
