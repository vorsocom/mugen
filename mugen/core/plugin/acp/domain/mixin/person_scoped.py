"""Provides a domain entity for person scoping."""

__all__ = ["PersonScopedDEMixin"]

import uuid
from dataclasses import dataclass
from typing import Type


@dataclass
class PersonScopedDEMixin:
    """A domain entity for person scoping."""

    person_id: uuid.UUID | None = None

    person: Type["PersonDE"] | None = None  # type: ignore
