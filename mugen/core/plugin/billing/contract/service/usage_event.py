"""Provides a service contract for UsageEventDE-related services."""

__all__ = ["IUsageEventService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import UsageEventDE


class IUsageEventService(
    ICrudService[UsageEventDE],
    ABC,
):
    """A service contract for UsageEventDE-related services."""
