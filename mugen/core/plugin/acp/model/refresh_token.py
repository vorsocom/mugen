"""Provides and ORM for refresh tokens."""

__all__ = ["RefreshToken"]

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.plugin.acp.model.mixin.user_scoped import UserScopedMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class RefreshToken(ModelBase, UserScopedMixin):
    """An ORM for refresh tokens."""

    __tablename__ = "admin_refresh_token"

    token_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
    )

    token_jti: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        unique=True,
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    user: Mapped["User"] = relationship(  # type: ignore
        back_populates="refresh_tokens",
    )

    __table_args__ = (
        Index(
            "ix_refresh_token__user_id_expires_at",
            "user_id",
            "expires_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"RefreshToken(id={self.id!r})"
