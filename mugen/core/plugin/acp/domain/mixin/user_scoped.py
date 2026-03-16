"""Provides a domain entity for user scoping."""

__all__ = ["UserScopedDEMixin"]

import uuid
from dataclasses import dataclass
from typing import Type


@dataclass
class UserScopedDEMixin:
    """A domain entity for user scoping."""

    user_id: uuid.UUID | None = None

    user: Type["UserDE"] | None = None  # type: ignore
