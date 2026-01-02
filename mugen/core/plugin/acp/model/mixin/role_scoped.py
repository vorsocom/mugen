"""Provides an SQLAlchemy declarative mixin for implementing role scoping."""

__all__ = ["RoleScopedMixin"]

import uuid

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column


class RoleScopedMixin:  # pylint: disable=too-few-public-methods
    """An SQLAlchemy declarative mixin for implementing role scoping."""

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )
