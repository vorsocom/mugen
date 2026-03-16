"""Provides a service contract for KpiThresholdDE-related services."""

__all__ = ["IKpiThresholdService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_reporting.domain import KpiThresholdDE


class IKpiThresholdService(
    ICrudService[KpiThresholdDE],
    ABC,
):
    """A service contract for KpiThresholdDE-related services."""
