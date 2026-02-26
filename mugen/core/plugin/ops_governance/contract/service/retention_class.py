"""Provides a service contract for RetentionClass services."""

__all__ = ["IRetentionClassService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_governance.domain import RetentionClassDE


class IRetentionClassService(ICrudService[RetentionClassDE], ABC):
    """A service contract for lifecycle retention class resources."""
