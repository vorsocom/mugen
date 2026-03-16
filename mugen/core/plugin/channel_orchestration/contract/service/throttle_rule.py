"""Provides a service contract for ThrottleRuleDE-related services."""

__all__ = ["IThrottleRuleService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.channel_orchestration.domain import ThrottleRuleDE


class IThrottleRuleService(ICrudService[ThrottleRuleDE], ABC):
    """A service contract for ThrottleRuleDE-related services."""
