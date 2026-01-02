"""Provides a domain entity for the Person DB model."""

__all__ = ["PersonDE"]

from dataclasses import dataclass
from typing import Type

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class PersonDE(BaseDE):
    """A domain entity for the Person DB model."""

    first_name: str | None = None

    last_name: str | None = None

    user: Type["UserDE"] | None = None  # type: ignore
