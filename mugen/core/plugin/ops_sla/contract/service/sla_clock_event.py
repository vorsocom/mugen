"""Provides a service contract for SlaClockEventDE-related services."""

__all__ = ["ISlaClockEventService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_sla.domain import SlaClockEventDE


class ISlaClockEventService(
    ICrudService[SlaClockEventDE],
    ABC,
):
    """A service contract for SlaClockEventDE-related services."""
