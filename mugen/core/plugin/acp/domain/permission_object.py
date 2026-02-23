"""Provides a domain entity for the PermissionObject DB model."""

__all__ = ["PermissionObjectDE"]

from dataclasses import dataclass
from typing import Sequence

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class PermissionObjectDE(BaseDE):
    """A domain entity for the PermissionObject DB model."""

    namespace: str | None = None

    name: str | None = None

    status: str | None = None

    permission_entries: Sequence["PermissionEntryDE"] | None = None  # type: ignore
