"""Provides an ORM for permission entries."""

__all__ = ["PermissionEntry"]

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.plugin.acp.model.mixin.role_scoped import RoleScopedMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class PermissionEntry(ModelBase, RoleScopedMixin, TenantScopedMixin):
    """An ORM for permission entries."""

    __tablename__ = "admin_permission_entry"

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

    permission_object: Mapped["PermissionObject"] = relationship(  # type: ignore
        back_populates="permission_entries",
    )

    permission_type: Mapped["PermissionType"] = relationship(  # type: ignore
        back_populates="permission_entries",
    )

    role: Mapped["Role"] = relationship(  # type: ignore
        back_populates="permission_entries",
    )

    tenant: Mapped["Tenant"] = relationship(  # type: ignore
        back_populates="permission_entries",
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
            name="fkx_permission_entry__tenant_role",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_permission_entry__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "role_id",
            "permission_object_id",
            "permission_type_id",
            name="ux_permission_entry__tenant_role_object_type",
        ),
        Index(
            "ix_permission_entry__tenant_role",
            "tenant_id",
            "role_id",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"PermissionEntry(id={self.id!r})"
