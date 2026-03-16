"""Provides a service contract for OrchestrationEventDE-related services."""

__all__ = ["IOrchestrationEventService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.channel_orchestration.domain import OrchestrationEventDE


class IOrchestrationEventService(ICrudService[OrchestrationEventDE], ABC):
    """A service contract for OrchestrationEventDE-related services."""
