"""Provides a service contract for ScorecardPolicyDE-related services."""

__all__ = ["IScorecardPolicyService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import ScorecardPolicyDE


class IScorecardPolicyService(
    ICrudService[ScorecardPolicyDE],
    ABC,
):
    """A service contract for ScorecardPolicyDE-related services."""
