"""Provides a service contract for ReportDefinitionDE-related services."""

__all__ = ["IReportDefinitionService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_reporting.domain import ReportDefinitionDE


class IReportDefinitionService(
    ICrudService[ReportDefinitionDE],
    ABC,
):
    """A service contract for ReportDefinitionDE-related services."""
