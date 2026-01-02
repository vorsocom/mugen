"""Provides an ORM for roles."""

__all__ = ["Role"]

from typing import List

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class Role(ModelBase, TenantScopedMixin):
    """An ORM for roles."""

    __tablename__ = "admin_role"

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

    tenant: Mapped["Tenant"] = relationship(  # type: ignore
        back_populates="roles",
    )

    permission_entries: Mapped[List["PermissionEntry"]] = relationship(  # type: ignore
        back_populates="role",
    )

    role_memberships: Mapped[List["RoleMembership"]] = relationship(  # type: ignore
        back_populates="role",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(namespace)) > 0",
            name="ck_role__namespace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_role__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_role__display_name_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_role__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "namespace",
            "name",
            name="ux_role__tenant_namespace_name",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"Role(id={self.id!r})"
