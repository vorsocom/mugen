"""Provides an ORM for global permission entries."""

__all__ = ["GlobalPermissionEntry"]

import uuid

from sqlalchemy import Boolean, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.global_role_scoped import GlobalRoleScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class GlobalPermissionEntry(ModelBase, GlobalRoleScopedMixin):
    """An ORM for global permission entries."""

    __tablename__ = "admin_global_permission_entry"

    permitted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_false(),
    )

    permission_object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_permission_object.id"),
        nullable=False,
    )

    permission_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_permission_type.id"),
        nullable=False,
    )

    global_role: Mapped["GlobalRole"] = relationship(  # type: ignore
        back_populates="global_permission_entries",
    )

    permission_object: Mapped["PermissionObject"] = relationship(  # type: ignore
        back_populates="global_permission_entries",
    )

    permission_type: Mapped["PermissionType"] = relationship(  # type: ignore
        back_populates="global_permission_entries",
    )

    __table_args__ = (
        UniqueConstraint(
            "global_role_id",
            "permission_object_id",
            "permission_type_id",
            name="ux_global_permission_entry__role_object_type",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"GlobalPermissionEntry(id={self.id!r})"
