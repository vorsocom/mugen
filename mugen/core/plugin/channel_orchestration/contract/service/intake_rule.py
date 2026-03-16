"""Provides a service contract for IntakeRuleDE-related services."""

__all__ = ["IIntakeRuleService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.channel_orchestration.domain import IntakeRuleDE


class IIntakeRuleService(ICrudService[IntakeRuleDE], ABC):
    """A service contract for IntakeRuleDE-related services."""
