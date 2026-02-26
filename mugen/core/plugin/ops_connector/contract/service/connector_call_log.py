"""Provides a service contract for ConnectorCallLogDE-related services."""

__all__ = ["IConnectorCallLogService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_connector.domain import ConnectorCallLogDE


class IConnectorCallLogService(
    ICrudService[ConnectorCallLogDE],
    ABC,
):
    """A service contract for ConnectorCallLogDE-related services."""
