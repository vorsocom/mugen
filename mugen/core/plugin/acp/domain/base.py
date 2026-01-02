"""Provides a base domain entity for all DB models."""

__all__ = ["BaseDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BaseDE:
    """A base domain entity for all DB models."""

    id: uuid.UUID | None = None

    created_at: datetime | None = None

    updated_at: datetime | None = None

    row_version: int | None = None
