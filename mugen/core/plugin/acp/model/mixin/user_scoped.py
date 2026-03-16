"""Provides an SQLAlchemy declarative mixin for implementing user scoping."""

__all__ = ["UserScopedMixin"]

import uuid

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class UserScopedMixin:  # pylint: disable=too-few-public-methods
    """An SQLAlchemy declarative mixin for implementing user scoping."""

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.admin_user.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
