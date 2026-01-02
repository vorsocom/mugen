"""Provides an SQLAlchemy declarative mixin for implementing person scoping."""

__all__ = ["PersonScopedMixin"]

import uuid

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class PersonScopedMixin:  # pylint: disable=too-few-public-methods
    """An SQLAlchemy declarative mixin for implementing person scoping."""

    person_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "mugen.admin_person.id",
        ),
        nullable=False,
        index=True,
    )
