"""Provides a service contract for SlaBreachEventDE-related services."""

__all__ = ["ISlaBreachEventService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_sla.domain import SlaBreachEventDE


class ISlaBreachEventService(
    ICrudService[SlaBreachEventDE],
    ABC,
):
    """A service contract for SlaBreachEventDE-related services."""
