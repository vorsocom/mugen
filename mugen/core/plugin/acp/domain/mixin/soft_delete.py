"""Provides a domain entity for soft delete scoping."""

__all__ = ["SoftDeleteDEMixin"]

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SoftDeleteDEMixin:
    """A domain entity for soft delete scoping."""

    deleted_at: datetime | None = None

    deleted_by_user_id: uuid.UUID | None = None
