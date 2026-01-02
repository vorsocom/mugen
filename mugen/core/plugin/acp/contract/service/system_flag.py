"""Provides a service contract for SystemFlag-related services."""

__all__ = ["ISystemFlagService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import SystemFlagDE


class ISystemFlagService(
    ICrudService[SystemFlagDE],
    ABC,
):
    """A service contract for SystemFlag-related services."""
