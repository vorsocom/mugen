"""Provides a service contract for ExportItemDE-related services."""

__all__ = ["IExportItemService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_reporting.domain import ExportItemDE


class IExportItemService(
    ICrudService[ExportItemDE],
    ABC,
):
    """A service contract for read-only export item ledger access."""
