"""Provides an SQLAlchemy declarative base for defining relational database models."""

__all__ = ["ModelBase"]

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

func: callable


class ModelBase(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Base class for ORMs."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date_created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    date_modified: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
