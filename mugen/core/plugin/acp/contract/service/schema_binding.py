"""Provides a service contract for SchemaBinding-related services."""

__all__ = ["ISchemaBindingService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import SchemaBindingDE


class ISchemaBindingService(ICrudService[SchemaBindingDE], ABC):
    """A service contract for schema binding services."""
