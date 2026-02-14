"""Provides a service contract for MeterDefinitionDE-related services."""

__all__ = ["IMeterDefinitionService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_metering.domain import MeterDefinitionDE


class IMeterDefinitionService(
    ICrudService[MeterDefinitionDE],
    ABC,
):
    """A service contract for MeterDefinitionDE-related services."""
