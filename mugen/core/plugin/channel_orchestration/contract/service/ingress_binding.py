"""Provides a service contract for IngressBindingDE-related services."""

__all__ = ["IIngressBindingService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.channel_orchestration.domain import IngressBindingDE


class IIngressBindingService(ICrudService[IngressBindingDE], ABC):
    """A service contract for IngressBindingDE-related services."""
