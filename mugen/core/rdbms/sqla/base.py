"""Provides an SQLAlchemy declarative base for defining relational database models."""

__all__ = ["ModelBase"]

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


# pylint: disable=too-few-public-methods
class ModelBase(DeclarativeBase):
    """Base class for ORMs."""

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda _: str(uuid.uuid4())
    )
    # pylint: disable=not-callable
    date_created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    date_modified: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    seed_data: Mapped[bool] = mapped_column(Boolean, default=False)
