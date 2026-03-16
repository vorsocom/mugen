"""Provides a domain entity for role scoping."""

__all__ = ["RoleScopedDEMixin"]

import uuid
from dataclasses import dataclass
from typing import Type


@dataclass
class RoleScopedDEMixin:
    """A domain entity for role scoping."""

    role_id: uuid.UUID | None = None

    role: Type["RoleDE"] | None = None  # type: ignore
