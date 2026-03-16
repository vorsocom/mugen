"""Provides a domain entity for the PermissionType DB model."""

__all__ = ["PermissionTypeDE"]

from dataclasses import dataclass
from typing import Sequence

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class PermissionTypeDE(BaseDE):
    """A domain entity for the PermissionType DB model."""

    namespace: str | None = None

    name: str | None = None

    status: str | None = None

    permission_entries: Sequence["PermissionEntryDE"] | None = None  # type: ignore
