"""Provides a service contract for PolicyDecisionLogDE-related services."""

__all__ = ["IPolicyDecisionLogService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_governance.domain import PolicyDecisionLogDE


class IPolicyDecisionLogService(ICrudService[PolicyDecisionLogDE], ABC):
    """A service contract for PolicyDecisionLogDE-related services."""
