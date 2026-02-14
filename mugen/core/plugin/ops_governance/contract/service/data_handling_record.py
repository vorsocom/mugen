"""Provides a service contract for DataHandlingRecordDE-related services."""

__all__ = ["IDataHandlingRecordService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_governance.domain import DataHandlingRecordDE


class IDataHandlingRecordService(ICrudService[DataHandlingRecordDE], ABC):
    """A service contract for DataHandlingRecordDE-related services."""
