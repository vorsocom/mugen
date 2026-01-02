"""Provides an SQLAlchemy declarative mixin for implementing global role scoping."""

__all__ = ["GlobalRoleScopedMixin"]

import uuid

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class GlobalRoleScopedMixin:  # pylint: disable=too-few-public-methods
    """An SQLAlchemy declarative mixin for implementing global role scoping."""

    global_role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.admin_global_role.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
