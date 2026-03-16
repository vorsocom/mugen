"""Provides a service contract for RetentionClass services."""

__all__ = ["IRetentionClassService"]

import uuid
from abc import ABC, abstractmethod

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_governance.domain import RetentionClassDE


class IRetentionClassService(ICrudService[RetentionClassDE], ABC):
    """A service contract for lifecycle retention class resources."""

    @abstractmethod
    async def resolve_active_for_resource_type(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
    ) -> RetentionClassDE | None:
        """Resolve a single active retention class for tenant + resource type."""
