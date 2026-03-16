"""Provides a service contract for RoutingRuleDE-related services."""

__all__ = ["IRoutingRuleService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.channel_orchestration.domain import RoutingRuleDE


class IRoutingRuleService(ICrudService[RoutingRuleDE], ABC):
    """A service contract for RoutingRuleDE-related services."""
