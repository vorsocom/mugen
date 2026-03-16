"""Provides a service contract for RatedUsageDE-related services."""

__all__ = ["IRatedUsageService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_metering.domain import RatedUsageDE


class IRatedUsageService(
    ICrudService[RatedUsageDE],
    ABC,
):
    """A service contract for RatedUsageDE-related services."""
