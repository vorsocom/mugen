"""Provides an SQLAlchemy declarative mixin for implementing soft deleting."""

__all__ = ["SoftDeleteMixin"]

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class SoftDeleteMixin:  # pylint: disable=too-few-public-methods
    """An SQLAlchemy declarative mixin for implementing soft deleting."""

    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=True,
    )

    deleted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id"),
        nullable=True,
    )
