"""Provides a service contract for SlaClockDefinitionDE-related services."""

__all__ = ["ISlaClockDefinitionService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_sla.domain import SlaClockDefinitionDE


class ISlaClockDefinitionService(
    ICrudService[SlaClockDefinitionDE],
    ABC,
):
    """A service contract for SlaClockDefinitionDE-related services."""
