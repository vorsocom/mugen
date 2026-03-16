"""Provides an SQLAlchemy declarative base for defining relational database models."""

__all__ = ["ModelBase"]

from datetime import datetime
import uuid

from sqlalchemy import BigInteger, DateTime
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ModelBase(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Base class for ORMs."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa_text("now()"),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa_text("now()"),
        nullable=False,
    )

    row_version: Mapped[int] = mapped_column(
        BigInteger,
        server_default=sa_text("1"),
        nullable=False,
    )
