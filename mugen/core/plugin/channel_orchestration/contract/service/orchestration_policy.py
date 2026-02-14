"""Provides a service contract for OrchestrationPolicyDE-related services."""

__all__ = ["IOrchestrationPolicyService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.channel_orchestration.domain import OrchestrationPolicyDE


class IOrchestrationPolicyService(ICrudService[OrchestrationPolicyDE], ABC):
    """A service contract for OrchestrationPolicyDE-related services."""
