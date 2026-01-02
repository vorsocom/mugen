"""Provides an ORM for users."""

__all__ = ["User"]

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.plugin.acp.model.mixin.person_scoped import PersonScopedMixin
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class User(ModelBase, PersonScopedMixin, SoftDeleteMixin):
    """An ORM for users."""

    __tablename__ = "admin_user"

    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    locked_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id"),
        nullable=True,
    )

    password_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    password_changed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id"),
        nullable=True,
    )

    username: Mapped[str] = mapped_column(
        CITEXT(128),
        unique=True,
        index=True,
        nullable=False,
    )

    login_email: Mapped[str] = mapped_column(
        CITEXT(254),
        unique=True,
        index=True,
        nullable=False,
    )

    last_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    failed_login_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    token_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(  # type: ignore
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    person: Mapped["Person"] = relationship(  # type: ignore
        back_populates="user",
    )

    tenant_memberships: Mapped[list["TenantMembership"]] = relationship(  # type: ignore
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    global_role_memberships: Mapped[list["GlobalRoleMembership"]] = relationship(  # type: ignore
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    role_memberships: Mapped[list["RoleMembership"]] = relationship(  # type: ignore
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "NOT (locked_at IS NOT NULL AND locked_by_user_id IS NULL)",
            name="ck_user__not_locked_and_not_locked_by_user_id",
        ),
        CheckConstraint(
            "NOT (password_changed_at IS NOT NULL AND password_changed_by_user_id IS"
            " NULL)",
            name="ck_user__not_password_changed_and_not_password_changed_by",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_user__not_deleted_and_not_deleted_by",
        ),
        CheckConstraint(
            "failed_login_count >= 0",
            name="ck_user__failed_login_count_nonnegative",
        ),
        CheckConstraint(
            "length(btrim(username)) > 0",
            name="ck_user__username_nonempty",
        ),
        CheckConstraint(
            "length(btrim(login_email)) > 0",
            name="ck_user__login_email_nonempty",
        ),
        CheckConstraint(
            "token_version >= 0",
            name="ck_user__token_version_nonnegative",
        ),
        UniqueConstraint(
            "person_id",
            name="ux_user__person_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!r})"
