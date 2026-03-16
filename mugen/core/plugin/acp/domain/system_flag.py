"""Provides a domain entity for the SystemFlag DB model."""

__all__ = ["SystemFlagDE"]

from dataclasses import dataclass

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class SystemFlagDE(BaseDE):
    """A domain entity for the Person DB model."""

    namespace: str | None = None

    name: str | None = None

    description: str | None = None

    is_set: bool | None = None
