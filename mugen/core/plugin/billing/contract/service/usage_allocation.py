"""Provides a service contract for UsageAllocationDE-related services."""

__all__ = ["IUsageAllocationService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import UsageAllocationDE


class IUsageAllocationService(
    ICrudService[UsageAllocationDE],
    ABC,
):
    """A service contract for UsageAllocationDE-related services."""
