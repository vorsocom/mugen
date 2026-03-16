"""Provides a domain entity for global role scoping."""

__all__ = ["GlobalRoleScopedDEMixin"]

import uuid
from dataclasses import dataclass
from typing import Type


@dataclass
class GlobalRoleScopedDEMixin:
    """A domain entity for global role scoping."""

    global_role_id: uuid.UUID | None = None

    global_role: Type["GlobalRoleDE"] | None = None  # type: ignore
