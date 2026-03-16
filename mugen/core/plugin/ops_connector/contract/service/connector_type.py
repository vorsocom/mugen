"""Provides a service contract for ConnectorTypeDE-related services."""

__all__ = ["IConnectorTypeService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_connector.domain import ConnectorTypeDE


class IConnectorTypeService(
    ICrudService[ConnectorTypeDE],
    ABC,
):
    """A service contract for ConnectorTypeDE-related services."""
