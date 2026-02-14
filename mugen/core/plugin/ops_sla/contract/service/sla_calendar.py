"""Provides a service contract for SlaCalendarDE-related services."""

__all__ = ["ISlaCalendarService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_sla.domain import SlaCalendarDE


class ISlaCalendarService(
    ICrudService[SlaCalendarDE],
    ABC,
):
    """A service contract for SlaCalendarDE-related services."""
